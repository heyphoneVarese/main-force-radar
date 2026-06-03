<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useMediaQuery } from '@vueuse/core'
import { dashboardApi, fundsApi, holdingsApi } from '../api/client'
import type {
  DashboardRadarResponse,
  Fund,
  Holding,
  HoldingsCapitalMigrationResponse,
  HoldingFactsSummary,
  TopFunds,
} from '../types'
// Phase 2:在 CRUD 下面叠加 4 张分析卡(我的事实摘要 / 主力雷达 /
// 基金候选 / 持仓映射)。从 Dashboard 迁过来,原 fetch + 状态机沿用。
import HoldingMappings from '../components/dashboard/HoldingMappings.vue'
import HoldingCapitalMigration from '../components/dashboard/HoldingCapitalMigration.vue'
import MainRadar from '../components/dashboard/MainRadar.vue'
import MarketTopFunds from '../components/dashboard/MarketTopFunds.vue'
import MyHoldingsTable from '../components/dashboard/MyHoldingsTable.vue'

// < 768px → 卡片;>= 768px → 表格
const isMobile = useMediaQuery('(max-width: 768px)')

const loading = ref(false)
const holdings = ref<Holding[]>([])
const funds = ref<Fund[]>([])

const dialogVisible = ref(false)
const isEditing = ref(false)
const editingFundCode = ref<string | null>(null)
const formRef = ref<FormInstance>()

const formData = reactive({
  fund_code: '',
  cost_nav: '',
  shares: '',
  bought_at: '',
  note: '',
})

const formRules: FormRules = {
  fund_code: [{ required: true, message: '请选择基金', trigger: 'change' }],
  cost_nav: [
    { required: true, message: '请输入成本净值', trigger: 'blur' },
    {
      validator: (_r, v: string, cb) => {
        const n = Number(v)
        if (!v || Number.isNaN(n) || n <= 0) cb(new Error('必须 > 0'))
        else cb()
      },
      trigger: 'blur',
    },
  ],
  shares: [
    { required: true, message: '请输入持有份额', trigger: 'blur' },
    {
      validator: (_r, v: string, cb) => {
        const n = Number(v)
        if (!v || Number.isNaN(n) || n <= 0) cb(new Error('必须 > 0'))
        else cb()
      },
      trigger: 'blur',
    },
  ],
  bought_at: [{ required: true, message: '请选择买入日期', trigger: 'change' }],
}

// fund_code → Fund 查询表(渲染表格时用)
const fundMap = computed(() => {
  const m = new Map<string, Fund>()
  for (const f of funds.value) m.set(f.fund_code, f)
  return m
})

// ==== PR13: 弹窗内嵌"新增基金" ====
//
// Element Plus el-select 的 filterable 默认按 label 做模糊匹配。我们用
// filter-method 重写过滤逻辑(同时按 code 和 name),并把搜索 query 存
// 到 ref,供 #empty slot 的 "未找到「{query}」" 提示用。
//
// 嵌套 dialog 不阻塞外层(append-to-body 默认 true)。提交成功后:
//   1. funds.value.push(created) — 立刻进入下拉选项
//   2. formData.fund_code = created.fund_code — 自动选中
//   3. 关闭嵌套 dialog,用户回到持仓表单继续填
//
// fund_type:spec 没列,但后端 schema 必填(min_length=1)。UI 不暴露,
// 提交时 hardcode "其他"。R6 简化;以后想编辑类型再加 PUT 接口。

const fundSearchQuery = ref('')

function onFundFilter(query: string): void {
  fundSearchQuery.value = query.trim()
}

const filteredFunds = computed(() => {
  const q = fundSearchQuery.value.toLowerCase()
  if (!q) return funds.value
  return funds.value.filter(
    (f) =>
      f.fund_code.includes(q) ||
      f.fund_name.toLowerCase().includes(q)
  )
})

const createFundDialogVisible = ref(false)
const newFundFormRef = ref<FormInstance>()
const newFundForm = reactive({
  fund_code: '',
  fund_name: '',
  related_sectors_input: '',
})

const newFundRules: FormRules = {
  fund_code: [
    { required: true, message: '请输入 6 位基金代码', trigger: 'blur' },
    { pattern: /^\d{6}$/, message: '必须是 6 位数字', trigger: 'blur' },
  ],
  fund_name: [
    { required: true, message: '请输入基金名称', trigger: 'blur' },
    { min: 1, max: 100, message: '长度 1-100', trigger: 'blur' },
  ],
}

function openCreateFund(): void {
  // 如果搜索 query 像 6 位代码,prefill
  const q = fundSearchQuery.value
  newFundForm.fund_code = /^\d{6}$/.test(q) ? q : ''
  newFundForm.fund_name = ''
  newFundForm.related_sectors_input = ''
  newFundFormRef.value?.clearValidate()
  createFundDialogVisible.value = true
}

async function submitNewFund(): Promise<void> {
  if (!newFundFormRef.value) return
  try {
    await newFundFormRef.value.validate()
  } catch {
    return
  }

  // 中英文逗号都接受,去空白,过滤空串
  const sectors = newFundForm.related_sectors_input
    .split(/[,，]/)
    .map((s) => s.trim())
    .filter(Boolean)

  try {
    const created = await fundsApi.create({
      fund_code: newFundForm.fund_code,
      fund_name: newFundForm.fund_name,
      fund_type: '其他',
      related_sectors: sectors.length > 0 ? sectors : null,
    })
    // 立刻加入本地 funds 列表,select 下拉马上能看到
    funds.value.push(created)
    // 自动选中
    formData.fund_code = created.fund_code
    // 清掉搜索词,关 dialog
    fundSearchQuery.value = ''
    createFundDialogVisible.value = false
    ElMessage.success(`已新增「${created.fund_name}」`)
  } catch (e) {
    const msg = (e as Error).message
    if (msg.includes('409') || msg.includes('already exists')) {
      ElMessage.warning('基金已存在,请直接选择')
    } else {
      ElMessage.error(`新增失败: ${msg}`)
    }
  }
}

async function loadAll() {
  loading.value = true
  try {
    const [hs, fs] = await Promise.all([holdingsApi.list(), fundsApi.list()])
    holdings.value = hs
    funds.value = fs
  } catch (e) {
    ElMessage.error(`加载失败: ${(e as Error).message}`)
  } finally {
    loading.value = false
  }
}

function resetForm() {
  formData.fund_code = ''
  formData.cost_nav = ''
  formData.shares = ''
  formData.bought_at = ''
  formData.note = ''
  formRef.value?.clearValidate()
}

function openAdd() {
  isEditing.value = false
  editingFundCode.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(h: Holding) {
  isEditing.value = true
  editingFundCode.value = h.fund_code
  formData.fund_code = h.fund_code
  formData.cost_nav = h.cost_nav
  formData.shares = h.shares
  formData.bought_at = h.bought_at
  formData.note = h.note ?? ''
  dialogVisible.value = true
}

async function submit() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return // 表单校验失败
  }
  try {
    if (isEditing.value && editingFundCode.value) {
      await holdingsApi.update(editingFundCode.value, {
        cost_nav: formData.cost_nav,
        shares: formData.shares,
        bought_at: formData.bought_at,
        note: formData.note || null,
      })
      ElMessage.success('已更新')
    } else {
      await holdingsApi.create({
        fund_code: formData.fund_code,
        cost_nav: formData.cost_nav,
        shares: formData.shares,
        bought_at: formData.bought_at,
        note: formData.note || null,
      })
      ElMessage.success('已添加')
    }
    dialogVisible.value = false
    await loadAll()
  } catch (e) {
    ElMessage.error(`操作失败: ${(e as Error).message}`)
  }
}

async function confirmDelete(h: Holding) {
  const name = fundMap.value.get(h.fund_code)?.fund_name ?? h.fund_code
  try {
    await ElMessageBox.confirm(`确定删除「${name}」的持仓?`, '二次确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }
  try {
    await holdingsApi.remove(h.fund_code)
    ElMessage.success('已删除')
    await loadAll()
  } catch (e) {
    ElMessage.error(`删除失败: ${(e as Error).message}`)
  }
}

// ===== Phase 2:分析卡 fetch =====
type AnalyticStatus = 'loading' | 'ready' | 'error'

const factsStatus = ref<AnalyticStatus>('loading')
const factsData = ref<HoldingFactsSummary | null>(null)
const factsError = ref('')

const radarStatus = ref<AnalyticStatus>('loading')
const radarData = ref<DashboardRadarResponse | null>(null)
const radarError = ref('')

const fundsTopStatus = ref<AnalyticStatus>('loading')
const fundsTopData = ref<TopFunds | null>(null)
const fundsTopError = ref('')

const capitalMigrationStatus = ref<AnalyticStatus>('loading')
const capitalMigrationData = ref<HoldingsCapitalMigrationResponse | null>(null)
const capitalMigrationError = ref('')

// 全局板块 rank 字典(给 HoldingMappings 显示"板块 #N");失败静默
const allSectorRanks = ref<Map<string, number>>(new Map())

// 客户端过滤至当前持仓 — fund_code 集合
const holdingCodes = computed<Set<string>>(() => new Set(holdings.value.map((h) => h.fund_code)))

function _analyticErr(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

function loadAnalytics(): void {
  void Promise.allSettled([
    dashboardApi.holdingsFacts().then(
      (d) => { factsData.value = d; factsStatus.value = 'ready' },
      (e) => { factsError.value = _analyticErr(e); factsStatus.value = 'error' },
    ),
    dashboardApi.radar('intraday', 20).then(
      (d) => { radarData.value = d; radarStatus.value = 'ready' },
      (e) => { radarError.value = _analyticErr(e); radarStatus.value = 'error' },
    ),
    dashboardApi.topFunds(20).then(
      (d) => { fundsTopData.value = d; fundsTopStatus.value = 'ready' },
      (e) => { fundsTopError.value = _analyticErr(e); fundsTopStatus.value = 'error' },
    ),
    dashboardApi.holdingsCapitalMigration(20).then(
      (d) => {
        capitalMigrationData.value = d
        capitalMigrationStatus.value = 'ready'
      },
      (e) => {
        capitalMigrationError.value = _analyticErr(e)
        capitalMigrationStatus.value = 'error'
      },
    ),
    dashboardApi.topSectors(100, 'all').then(
      (d) => {
        const m = new Map<string, number>()
        for (const s of d.sectors) m.set(s.sector_code, s.rank)
        allSectorRanks.value = m
      },
      () => { /* swallow */ },
    ),
  ])
}

onMounted(() => {
  void loadAll()
  loadAnalytics()
})
</script>

<template>
  <div v-loading="loading" class="min-h-[200px]">
    <!-- 标题栏 -->
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-2xl font-bold">
        我的持仓
        <span class="text-base font-normal text-gray-500">({{ holdings.length }})</span>
      </h2>
      <el-button type="primary" size="large" class="!min-h-[44px]" @click="openAdd">
        + 添加持仓
      </el-button>
    </div>

    <!-- 空态 -->
    <el-empty v-if="!loading && holdings.length === 0" description="还没有持仓,点击右上角「+ 添加持仓」开始" />

    <!-- 桌面端:表格 -->
    <el-table
      v-else-if="!isMobile"
      :data="holdings"
      stripe
      border
      class="rounded-lg"
    >
      <el-table-column prop="fund_code" label="代码" width="100" />
      <el-table-column label="名称" min-width="220">
        <template #default="{ row }">
          <span class="font-medium">{{ fundMap.get(row.fund_code)?.fund_name ?? '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag size="small">{{ fundMap.get(row.fund_code)?.fund_type ?? '—' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="板块" min-width="240">
        <template #default="{ row }">
          <el-tag
            v-for="s in fundMap.get(row.fund_code)?.related_sectors ?? []"
            :key="s"
            type="info"
            size="small"
            class="mr-1 mb-1"
          >{{ s }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="cost_nav" label="成本(元)" width="100" align="right" />
      <el-table-column prop="shares" label="份额" width="120" align="right" />
      <el-table-column prop="bought_at" label="买入日" width="110" />
      <el-table-column label="备注" min-width="120">
        <template #default="{ row }">
          <span class="text-gray-500">{{ row.note || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="confirmDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 移动端:卡片 -->
    <div v-else class="space-y-3">
      <el-card v-for="h in holdings" :key="h.fund_code" shadow="never" class="rounded-lg">
        <div class="flex items-start justify-between mb-2">
          <div class="flex-1 min-w-0">
            <div class="font-semibold truncate">
              {{ fundMap.get(h.fund_code)?.fund_name ?? h.fund_code }}
            </div>
            <div class="text-xs text-gray-500 mt-0.5">
              {{ h.fund_code }} · {{ fundMap.get(h.fund_code)?.fund_type ?? '—' }}
            </div>
          </div>
          <el-tag size="small" class="ml-2 shrink-0">{{ h.bought_at }}</el-tag>
        </div>

        <div class="flex flex-wrap gap-1 mb-3">
          <el-tag
            v-for="s in fundMap.get(h.fund_code)?.related_sectors ?? []"
            :key="s"
            type="info"
            size="small"
          >{{ s }}</el-tag>
        </div>

        <div class="grid grid-cols-2 gap-2 mb-3 text-sm">
          <div>
            <div class="text-gray-500 text-xs">成本(元)</div>
            <div class="font-mono">{{ h.cost_nav }}</div>
          </div>
          <div>
            <div class="text-gray-500 text-xs">份额</div>
            <div class="font-mono">{{ h.shares }}</div>
          </div>
        </div>

        <div v-if="h.note" class="text-sm text-gray-600 mb-3">备注:{{ h.note }}</div>

        <div class="flex gap-2">
          <el-button class="flex-1 !min-h-[44px]" @click="openEdit(h)">编辑</el-button>
          <el-button class="flex-1 !min-h-[44px]" type="danger" @click="confirmDelete(h)">
            删除
          </el-button>
        </div>
      </el-card>
    </div>

    <!-- 添加 / 编辑 对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEditing ? '编辑持仓' : '添加持仓'"
      :width="isMobile ? '92%' : '500px'"
      :close-on-click-modal="false"
    >
      <el-form
        ref="formRef"
        :model="formData"
        :rules="formRules"
        label-position="top"
      >
        <el-form-item label="基金" prop="fund_code">
          <el-select
            v-model="formData.fund_code"
            filterable
            :filter-method="onFundFilter"
            :disabled="isEditing"
            placeholder="搜索代码或名称"
            class="w-full"
          >
            <el-option
              v-for="f in filteredFunds"
              :key="f.fund_code"
              :label="`${f.fund_code} · ${f.fund_name}`"
              :value="f.fund_code"
            />
            <!-- 自定义空态:基金库没收录 → 直接新增 -->
            <template #empty>
              <div class="p-3">
                <p class="text-sm text-gray-600 mb-1">
                  未找到该基金<span v-if="fundSearchQuery">「<span class="font-mono">{{ fundSearchQuery }}</span>」</span>,是否新增到基金库?
                </p>
                <p class="text-xs text-gray-400 mb-2">
                  基金类型默认"其他";related_sectors 中文标签,以逗号分隔
                </p>
                <el-button
                  size="small"
                  type="primary"
                  class="!min-h-[40px]"
                  @click="openCreateFund"
                >
                  + 新增基金
                </el-button>
              </div>
            </template>
          </el-select>
        </el-form-item>

        <el-form-item label="成本净值(元)" prop="cost_nav">
          <el-input v-model="formData.cost_nav" placeholder="如 1.5234" />
        </el-form-item>

        <el-form-item label="持有份额" prop="shares">
          <el-input v-model="formData.shares" placeholder="如 1000.5" />
        </el-form-item>

        <el-form-item label="买入日期" prop="bought_at">
          <el-date-picker
            v-model="formData.bought_at"
            type="date"
            value-format="YYYY-MM-DD"
            :disabled-date="(d: Date) => d > new Date()"
            class="!w-full"
            placeholder="选择日期"
          />
        </el-form-item>

        <el-form-item label="备注">
          <el-input
            v-model="formData.note"
            type="textarea"
            :rows="2"
            placeholder="可选"
            maxlength="200"
            show-word-limit
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button class="!min-h-[44px]" @click="dialogVisible = false">取消</el-button>
        <el-button class="!min-h-[44px]" type="primary" @click="submit">提交</el-button>
      </template>
    </el-dialog>

    <!-- PR13:嵌套"新增基金"对话框 -->
    <el-dialog
      v-model="createFundDialogVisible"
      title="新增基金到基金库"
      :width="isMobile ? '92%' : '460px'"
      :close-on-click-modal="false"
      append-to-body
    >
      <el-form
        ref="newFundFormRef"
        :model="newFundForm"
        :rules="newFundRules"
        label-position="top"
      >
        <el-form-item label="基金代码" prop="fund_code">
          <el-input
            v-model="newFundForm.fund_code"
            placeholder="6 位数字,如 008281"
            maxlength="6"
          />
        </el-form-item>

        <el-form-item label="基金名称" prop="fund_name">
          <el-input
            v-model="newFundForm.fund_name"
            placeholder="如 国泰CES半导体芯片行业ETF联接A"
            maxlength="100"
            show-word-limit
          />
        </el-form-item>

        <el-form-item label="关联板块(可选)">
          <el-input
            v-model="newFundForm.related_sectors_input"
            placeholder="半导体,芯片,人工智能"
            maxlength="200"
            show-word-limit
          />
          <p class="text-xs text-gray-400 mt-1">
            中英文逗号分隔;空着也可以,之后再补
          </p>
        </el-form-item>

        <p class="text-xs text-gray-400 -mt-2 mb-2">
          基金类型默认填"其他";新增成功后会自动选中并回到持仓表单
        </p>
      </el-form>

      <template #footer>
        <el-button
          class="!min-h-[44px]"
          @click="createFundDialogVisible = false"
        >
          取消
        </el-button>
        <el-button
          class="!min-h-[44px]"
          type="primary"
          @click="submitNewFund"
        >
          确认新增
        </el-button>
      </template>
    </el-dialog>

    <!-- ===== Phase 2:持仓分析卡(原 Dashboard 4 张卡迁过来) ===== -->
    <section class="mt-8 space-y-4">
      <header class="border-t pt-6">
        <h3 class="text-lg font-semibold text-gray-900">持仓分析</h3>
        <p class="text-xs text-gray-500 mt-1">
          我的事实摘要 · 主力雷达 · 基金候选 · 持仓映射
        </p>
      </header>

      <MyHoldingsTable
        :status="factsStatus"
        :data="factsData"
        :error="factsError"
      />

      <HoldingCapitalMigration
        :status="capitalMigrationStatus"
        :data="capitalMigrationData"
        :error="capitalMigrationError"
      />

      <MainRadar
        :status="radarStatus"
        :data="radarData"
        :error="radarError"
      />

      <MarketTopFunds
        :status="fundsTopStatus"
        :data="fundsTopData"
        :error="fundsTopError"
        :holding-codes="holdingCodes"
      />

      <HoldingMappings
        :status="fundsTopStatus"
        :data="fundsTopData"
        :error="fundsTopError"
        :holding-codes="holdingCodes"
        :sector-rank-by-code="allSectorRanks"
      />
    </section>
  </div>
</template>
