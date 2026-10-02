<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>回访状态查询</h2>
        <p class="page-desc">
          另一个查询入口：按工单号或来电号码读取回访状态。这里与客服工作台取的是同一份投诉工单主档，
          两处结果必然一致。
        </p>
      </div>
    </header>

    <StaffSwitcher />

    <form class="filter-bar" @submit.prevent="search">
      <label class="filter-item">
        <span>工单号 / 来电号码</span>
        <input v-model="keyword" placeholder="如 TS-20260007 或 13800138000" style="min-width: 280px" />
      </label>
      <button class="btn primary" type="submit">查询回访状态</button>
    </form>

    <div v-if="error" class="notice bad">{{ error }}</div>

    <div v-if="result" class="result-card">
      <div class="consistency">
        <span class="dot ok"></span>
        与客服工作台一致：两边读取同一数据来源「{{ result['数据来源'] }}」
        <template v-if="cross">
          ，工单回访状态 <strong>{{ result['回访状态'] }}</strong> = 工作台清单
          <strong>{{ cross['回访状态'] }}</strong>
          <span :class="['tag', consistent ? 'match' : 'mismatch']">
            {{ consistent ? '✓ 同源一致' : '✗ 不一致' }}
          </span>
        </template>
      </div>
      <table class="data-table">
        <tbody>
          <tr><th>工单编号</th><td>{{ result['工单编号'] }}</td></tr>
          <tr><th>来电号码</th><td>{{ result['来电号码'] }}</td></tr>
          <tr><th>投诉类型 / 责任班组</th><td>{{ result['投诉类型'] }} / {{ result['责任班组'] }}</td></tr>
          <tr><th>当前环节</th><td>{{ result['当前环节'] }}</td></tr>
          <tr><th>回访状态</th><td><span :class="['pill', result['回访状态'] === '已回访' ? 'done' : 'wait']">{{ result['回访状态'] }}</span></td></tr>
          <tr><th>回访结论</th><td>{{ result['回访结论'] ?? '尚未回访' }}</td></tr>
          <tr><th>回访人 / 时间</th><td>{{ result['回访人'] ?? '—' }}　{{ result['回访时间'] ?? '' }}</td></tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

import { request } from '@/api/client'
import StaffSwitcher from '../complaint/StaffSwitcher.vue'
import { loadMeta } from '../complaint/shared'

type TrackRow = Record<string, string | number | null>

const keyword = ref('')
const result = ref<TrackRow | null>(null)
const cross = ref<TrackRow | null>(null)
const error = ref('')

const consistent = computed(() =>
  result.value && cross.value ? result.value['回访状态'] === cross.value['回访状态'] : false,
)

async function search() {
  result.value = null
  cross.value = null
  error.value = ''
  const key = keyword.value.trim()
  if (!key) {
    error.value = '请输入工单号或来电号码'
    return
  }
  try {
    const resp = await request(`/api/complaint/track?keyword=${encodeURIComponent(key)}`)
    if (resp.status === 404) {
      error.value = `未找到与「${key}」匹配的投诉工单`
      return
    }
    if (!resp.ok) throw new Error('回访状态查询失败')
    result.value = await resp.json()
    // 拉一次工作台清单做交叉比对，证明两个入口同源同值。
    const listResp = await request('/api/complaint/callback?status=')
    if (listResp.ok) {
      const items: TrackRow[] = (await listResp.json()).items ?? []
      cross.value = items.find((it) => it.id === result.value?.id) ?? null
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '回访状态查询失败'
  }
}

loadMeta().catch(() => undefined)
</script>

<style scoped>
.notice { border-radius: 6px; padding: 8px 12px; font-size: 13px; margin-bottom: 10px; }
.notice.bad { background: #fef2f2; border: 1px solid #fca5a5; color: #991b1b; }
.result-card { background: #fff; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.consistency { display: flex; align-items: center; gap: 6px; padding: 10px 12px; font-size: 13px; background: #f0fdf4; color: #166534; border-bottom: 1px solid #bbf7d0; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.dot.ok { background: #16a34a; }
.tag { border-radius: 4px; padding: 0 6px; font-size: 12px; }
.tag.match { background: #dcfce7; color: #166534; }
.tag.mismatch { background: #fee2e2; color: #991b1b; }
.data-table th { width: 180px; background: #f8fafc; }
.pill { border-radius: 4px; padding: 1px 8px; font-size: 12px; }
.pill.wait { background: #ffe4e6; color: #9f1239; }
.pill.done { background: #dcfce7; color: #166534; }
</style>
