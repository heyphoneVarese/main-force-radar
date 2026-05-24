<script setup lang="ts">
</script>

<template>
  <div class="min-h-screen bg-gray-50 p-8">
    <h1 class="text-3xl font-bold text-gray-900">主力风向标</h1>
    <p class="mt-2 text-gray-600">Main Force Radar · Phase 1 项目初始化完成</p>

    <el-card class="mt-6 max-w-xl">
      <p class="text-sm text-gray-700">
        后端健康检查:
        <a class="text-blue-600 underline" href="http://localhost:8000/health" target="_blank">
          /health
        </a>
      </p>
      <p class="mt-1 text-sm text-gray-700">
        API 文档:
        <a class="text-blue-600 underline" href="http://localhost:8000/docs" target="_blank">
          /docs
        </a>
      </p>
    </el-card>
  </div>
</template>
