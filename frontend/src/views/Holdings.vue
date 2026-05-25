<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useMediaQuery } from '@vueuse/core'
import { fundsApi, holdingsApi } from '../api/client'
import type { Fund, Holding } from '../types'

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

onMounted(loadAll)
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
            :disabled="isEditing"
            placeholder="搜索代码或名称(filterable)"
            class="w-full"
          >
            <el-option
              v-for="f in funds"
              :key="f.fund_code"
              :label="`${f.fund_code} · ${f.fund_name}`"
              :value="f.fund_code"
            />
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
  </div>
</template>
