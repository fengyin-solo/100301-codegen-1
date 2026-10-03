<template>
  <section class="page" data-module="complaint">
    <header class="page-head">
      <div>
        <h2>投诉工单管理</h2>
        <p class="page-desc">断站、掉话、资费投诉一条流水：受理派班、认领处置、值班长确认、回访归档，重复来电自动并单。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="showCreate = !showCreate">受理客户投诉</button>
        <button class="btn" type="button" @click="exportRows">导出投诉工单清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="showCreate" class="filter-bar" @submit.prevent="submitCreate">
      <label class="filter-item">
        <span>客户号码</span>
        <input v-model="createForm['客户号码']" placeholder="必填，如 13800000006" />
      </label>
      <label class="filter-item">
        <span>投诉类型</span>
        <select v-model="createForm['投诉类型']">
          <option v-for="item in complaintTypes" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>投诉内容</span>
        <input v-model="createForm['投诉内容']" placeholder="必填，客户反映的问题" />
      </label>
      <label class="filter-item">
        <span>受理人</span>
        <input v-model="createForm['受理人']" placeholder="值班客服" />
      </label>
      <button class="btn primary" type="submit">提交受理</button>
    </form>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>工单编号 / 客户号码</span>
        <input v-model="filters.keyword" placeholder="按工单编号或客户号码检索" />
      </label>
      <label class="filter-item">
        <span>责任班组</span>
        <select v-model="filters.team">
          <option value="">全部班组</option>
          <option v-for="item in teams" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>工单状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in rowActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="openAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="queryCallback(row)">回访状态</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无投诉工单数据，可先受理客户投诉</td>
        </tr>
      </tbody>
    </table>

    <form v-if="activeAction" class="filter-bar action-panel" @submit.prevent="submitAction">
      <span class="panel-title">{{ activeRow?.['工单编号'] }} · {{ activeAction }}</span>
      <label v-for="field in actionFields[activeAction] ?? []" :key="field.key" class="filter-item">
        <span>{{ field.label }}</span>
        <select v-if="field.options" v-model="actionForm[field.key]">
          <option value="">请选择</option>
          <option v-for="option in field.options" :key="option" :value="option">{{ option }}</option>
        </select>
        <input v-else v-model="actionForm[field.key]" :placeholder="field.label" />
      </label>
      <button class="btn primary" type="submit">确认{{ activeAction }}</button>
      <button class="btn ghost" type="button" @click="activeAction = ''">取消</button>
    </form>

    <section class="workbench">
      <h3>客服工作台 · 回访清单</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in callbackColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in callbacks" :key="String(item.id)">
            <td v-for="column in callbackColumns" :key="column">{{ item[column] || '—' }}</td>
          </tr>
          <tr v-if="!callbacks.length">
            <td :colspan="callbackColumns.length" class="empty-state">暂无回访任务</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条投诉工单记录</span>
      <span v-if="callbackInfo" class="notice-text">{{ callbackInfo }}</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/complaint'
const columns = ["工单编号", "客户号码", "投诉类型", "受理时间", "责任班组", "追加次数", "工单状态"]
const callbackColumns = ["工单编号", "客户号码", "责任班组", "回访状态", "回访结论", "回访时间"]
const statuses = ["待处置", "处置中", "待回访", "已归档"]
const complaintTypes = ["断站", "掉话", "资费"]
const teams = ["网络运维一班", "网络运维二班", "客服支撑班"]
const actionFields: Record<string, { key: string; label: string; options?: string[] }[]> = {
  认领工单: [
    { key: '操作人', label: '操作人' },
    { key: '所属班组', label: '所属班组', options: teams },
  ],
  提交处置: [
    { key: '操作人', label: '操作人' },
    { key: '所属班组', label: '所属班组', options: teams },
    { key: '处置结论', label: '处置结论' },
    { key: '值班长', label: '值班长确认人' },
  ],
  回访归档: [
    { key: '回访人', label: '回访人' },
    { key: '回访结论', label: '回访结论' },
  ],
}

const rows = ref<Row[]>([])
const callbacks = ref<Row[]>([])
const stats = ref<{ label: string; value: number }[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const callbackInfo = ref('')
const filters = ref<Record<string, string>>({})
const showCreate = ref(false)
const createForm = ref<Record<string, string>>({ 投诉类型: '断站' })
const activeAction = ref('')
const activeRow = ref<Row | null>(null)
const actionForm = ref<Record<string, string>>({})

function rowActions(row: Row): string[] {
  const map: Record<string, string[]> = { 待处置: ['认领工单'], 处置中: ['提交处置'], 待回访: ['回访归档'] }
  return map[String(row['工单状态'])] ?? []
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openAction(action: string, row: Row) {
  activeAction.value = action
  activeRow.value = row
  actionForm.value = {}
  errorMessage.value = ''
}

async function submitCreate() {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '投诉工单受理失败')
    }
    noticeMessage.value = payload.message
    createForm.value = { 投诉类型: '断站' }
    showCreate.value = false
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '投诉工单受理失败'
  }
}

async function submitAction() {
  if (!activeRow.value) return
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${activeRow.value.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action: activeAction.value, ...actionForm.value } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '工单动作未生效')
    }
    noticeMessage.value = payload.message
    activeAction.value = ''
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '投诉工单操作失败'
  }
}

async function queryCallback(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/callback`)
    if (!response.ok) {
      callbackInfo.value = `工单 ${row['工单编号']} 还没有生成回访记录`
      return
    }
    const record = await response.json()
    callbackInfo.value = `工单 ${record['工单编号']} 回访状态：${record['回访状态']}（与客服工作台清单同源）`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '回访状态读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(
    Object.fromEntries(Object.entries(filters.value).filter(([, value]) => value)),
  ).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('投诉工单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '投诉工单列表读取失败'
  }
}

async function reloadCallbacks() {
  try {
    const response = await request(`${ENDPOINT}/callbacks`)
    if (!response.ok) {
      throw new Error('回访清单读取失败')
    }
    const payload = await response.json()
    callbacks.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '回访清单读取失败'
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      throw new Error('工单统计读取失败')
    }
    const payload = await response.json()
    stats.value = payload.cards ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '工单统计读取失败'
  }
}

async function refreshAll() {
  await Promise.all([reload(), reloadCallbacks(), reloadStats()])
}

onMounted(refreshAll)
</script>

<style scoped>
.action-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
}
.panel-title {
  font-size: 13px;
  font-weight: 600;
  align-self: center;
}
.workbench {
  margin-top: 16px;
}
.workbench h3 {
  font-size: 14px;
  margin: 0 0 8px;
}
.notice-text {
  color: #067647;
}
</style>
