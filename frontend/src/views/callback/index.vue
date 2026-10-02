<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>客服工作台 · 待回访清单</h2>
        <p class="page-desc">
          处置经值班长确认后转入本清单；客服回填回访结论即归档，状态实时更新。
          本清单与「回访状态查询」读的是同一份投诉工单主档。
        </p>
      </div>
    </header>

    <StaffSwitcher />

    <div class="filter-bar">
      <label class="filter-item">
        <span>回访状态</span>
        <select v-model="status" @change="reload">
          <option value="待回访">待回访</option>
          <option value="已回访">已回访</option>
          <option value="">全部</option>
        </select>
      </label>
      <label class="filter-item">
        <span>工单号 / 号码</span>
        <input v-model="keyword" placeholder="检索后点查询" @keyup.enter="reload" />
      </label>
      <button class="btn" type="button" @click="reload">查询</button>
    </div>

    <div v-if="notice" :class="['notice', 'ok']">{{ notice }}</div>

    <table class="data-table">
      <thead>
        <tr>
          <th>工单编号</th><th>来电号码</th><th>投诉类型</th><th>责任班组</th>
          <th>当前环节</th><th>回访状态</th><th>回访结论</th><th>回访人</th><th>回访时间</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in items" :key="String(row.id)">
          <td>{{ row['工单编号'] }}</td>
          <td>{{ row['来电号码'] }}</td>
          <td>{{ row['投诉类型'] }}</td>
          <td>{{ row['责任班组'] }}</td>
          <td>{{ row['当前环节'] }}</td>
          <td><span :class="['pill', row['回访状态'] === '已回访' ? 'done' : 'wait']">{{ row['回访状态'] }}</span></td>
          <td class="cell-clip" :title="String(row['回访结论'] ?? '')">{{ row['回访结论'] ?? '—' }}</td>
          <td>{{ row['回访人'] ?? '—' }}</td>
          <td>{{ row['回访时间'] ?? '—' }}</td>
        </tr>
        <tr v-if="!items.length">
          <td colspan="9" class="empty-state">当前没有{{ status || '' }}工单</td>
        </tr>
      </tbody>
    </table>
    <footer class="page-foot"><span>共 {{ items.length }} 条（数据来源：投诉工单主档）</span></footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'
import StaffSwitcher from '../complaint/StaffSwitcher.vue'
import { loadMeta } from '../complaint/shared'

type Row = Record<string, string | number | null>

const items = ref<Row[]>([])
const status = ref('待回访')
const keyword = ref('')
const notice = ref('')

async function reload() {
  notice.value = ''
  const params = new URLSearchParams()
  if (status.value) params.set('status', status.value)
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  try {
    const resp = await request(`/api/complaint/callback?${params.toString()}`)
    if (!resp.ok) throw new Error('待回访清单读取失败')
    items.value = (await resp.json()).items ?? []
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '待回访清单读取失败'
  }
}

onMounted(async () => {
  await loadMeta()
  await reload()
})
</script>

<style scoped>
.cell-clip { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pill { border-radius: 4px; padding: 1px 8px; font-size: 12px; }
.pill.wait { background: #ffe4e6; color: #9f1239; }
.pill.done { background: #dcfce7; color: #166534; }
.notice { background: #fef2f2; border: 1px solid #fca5a5; color: #991b1b; border-radius: 6px; padding: 8px 12px; font-size: 13px; margin-bottom: 10px; }
</style>
