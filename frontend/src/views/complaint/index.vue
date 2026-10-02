<template>
  <section class="page" data-module="complaint">
    <header class="page-head">
      <div>
        <h2>客户投诉工单流水</h2>
        <p class="page-desc">
          断站、掉话、资费投诉统一受理，只能沿「待处置 → 处置中 → 待回访 → 已归档」单向流转；
          处置中须值班长确认，不可退回或越级；同号码当日重复来电只并单追加。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openAccept">受理投诉</button>
        <button class="btn" type="button" @click="runBackfill">补录存量归属</button>
      </div>
    </header>

    <StaffSwitcher />

    <div v-if="store.backfill" class="backfill-tip">
      存量补录：存量工单 {{ store.backfill.legacy_total }} 张，已补派责任班组
      {{ store.backfill.backfilled }} 张，待补 {{ store.backfill.missing_crew }} 张；历史处置/回访结论原样保留不回填。
    </div>

    <div class="stat-row">
      <article v-for="item in stages" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>工单号 / 号码</span>
        <input v-model="filters.keyword" placeholder="按工单号或来电号码检索" />
      </label>
      <label class="filter-item">
        <span>环节</span>
        <select v-model="filters.status">
          <option value="">全部环节</option>
          <option v-for="s in stageLabels" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>责任班组</span>
        <select v-model="filters.crew">
          <option value="">全部班组</option>
          <option v-for="c in crews" :key="c" :value="c">{{ c }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>投诉类型</span>
        <select v-model="filters.ctype">
          <option value="">全部类型</option>
          <option v-for="t in types" :key="t" :value="t">{{ t }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置</button>
    </form>

    <div v-if="notice" :class="['notice', notice.ok ? 'ok' : 'bad']">{{ notice.text }}</div>

    <table class="data-table">
      <thead>
        <tr>
          <th>工单编号</th>
          <th>来电号码</th>
          <th>投诉类型</th>
          <th>受理时间</th>
          <th>责任班组</th>
          <th>认领人</th>
          <th>当前环节</th>
          <th>处置结论</th>
          <th>值班长确认</th>
          <th>回访状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>
            {{ row['工单编号'] }}
            <span v-if="row['是否存量']" class="tag legacy">存量</span>
            <span v-if="row['归属补录']" class="tag backfill">补归属</span>
            <span v-if="(row['追加来电'] as CallRecord[] | undefined)?.length" class="tag merge">
              并单×{{ ((row['追加来电'] as CallRecord[] | undefined)?.length ?? 0) + 1 }}
            </span>
          </td>
          <td>{{ row['来电号码'] }}</td>
          <td>{{ row['投诉类型'] }}</td>
          <td>{{ row['受理时间'] }}</td>
          <td>{{ row['责任班组'] ?? '待补派' }}</td>
          <td>{{ row['认领人'] ?? '—' }}</td>
          <td><span :class="['stage', stageClass(row['status'])]">{{ row['status'] }}</span></td>
          <td class="cell-clip" :title="String(row['处置结论'] ?? '')">{{ row['处置结论'] ?? '—' }}</td>
          <td>{{ row['值班长确认人'] ?? '—' }}</td>
          <td>{{ row['回访状态'] }}</td>
          <td class="row-actions">
            <button
              v-for="act in (row['可执行动作'] as string[])"
              :key="act"
              class="link"
              type="button"
              @click="openAction(act, row)"
            >
              {{ act }}
            </button>
            <button class="link muted-link" type="button" @click="openDetail(row)">流水/追加</button>
            <span v-if="!row['可写'] && row['status'] !== '已归档'" class="readonly-hint" :title="String(row['权限说明'] ?? '')">
              只读
            </span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="11" class="empty-state">暂无符合条件的投诉工单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 张投诉工单</span>
    </footer>

    <!-- 受理弹窗 -->
    <div v-if="accepting" class="modal-mask" @click.self="accepting = false">
      <div class="modal">
        <h3>受理客户投诉</h3>
        <p class="modal-tip">以 {{ store.activeStaff?.姓名 }} 身份受理；同号码当日再次来电将自动并单追加。</p>
        <label class="form-item"><span>来电号码 *</span><input v-model="acceptForm.number" placeholder="如 13800138000" /></label>
        <label class="form-item">
          <span>投诉类型 *</span>
          <select v-model="acceptForm.ctype">
            <option value="">请选择</option>
            <option v-for="t in types" :key="t" :value="t">{{ t }}（派{{ crewOf(t) }}）</option>
          </select>
        </label>
        <label class="form-item"><span>反映内容 *</span><textarea v-model="acceptForm.content" rows="3" /></label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="accepting = false">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitAccept">提交受理</button>
        </div>
      </div>
    </div>

    <!-- 处置 / 回访 录入弹窗 -->
    <div v-if="modalAction" class="modal-mask" @click.self="modalAction = ''">
      <div class="modal">
        <h3>{{ modalAction }} · {{ modalRow?.['工单编号'] }}</h3>
        <p class="modal-tip">责任班组：{{ modalRow?.['责任班组'] }}　当前环节：{{ modalRow?.['status'] }}</p>
        <label v-if="modalAction === '填写处置结论'" class="form-item">
          <span>处置结论 *</span>
          <textarea v-model="modalText" rows="4" placeholder="填写本班组处置结论，提交后须值班长确认" />
        </label>
        <label v-if="modalAction === '回访归档'" class="form-item">
          <span>回访结论 *</span>
          <textarea v-model="modalText" rows="4" placeholder="客服回访结论，提交即归档并回写待回访清单" />
        </label>
        <p v-if="modalAction === '认领'">确认以 {{ store.activeStaff?.姓名 }} 认领该工单并进入处置中？</p>
        <p v-if="modalAction === '值班长确认'">处置结论经值班长确认后转客服待回访；该操作不可退回。</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="modalAction = ''">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitAction">确认</button>
        </div>
      </div>
    </div>

    <!-- 流水 / 追加来电 详情 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal wide">
        <h3>工单流水 · {{ detail['工单编号'] }}</h3>
        <p class="modal-tip">
          <span v-if="detail['归属补录']" class="tag backfill">存量已补派 {{ detail['责任班组'] }}</span>
          <span v-if="detail['历史处置结论']" class="tag legacy">历史结论保留</span>
        </p>
        <div v-if="detail['历史处置结论']" class="history-box">
          <strong>当时的处置结论（不按新口径回填）：</strong>{{ detail['历史处置结论'] }}
        </div>
        <h4>追加来电（{{ detail['追加来电']?.length ?? 0 }} 次）</h4>
        <table v-if="detail['追加来电']?.length" class="data-table sub">
          <thead><tr><th>序号</th><th>来电时间</th><th>反映内容</th><th>受理人</th></tr></thead>
          <tbody>
            <tr v-for="(c, i) in detail['追加来电']" :key="i">
              <td>{{ i + 1 }}</td><td>{{ c['来电时间'] }}</td><td>{{ c['反映内容'] }}</td><td>{{ c['受理人'] }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty-inline">当日无重复来电。</p>
        <h4>操作流水</h4>
        <ul class="timeline">
          <li v-for="(log, i) in detail['操作流水']" :key="i">
            <span class="log-time">{{ log['时间'] }}</span>
            <span class="log-stage">[{{ log['环节'] }}]</span>
            <strong>{{ log['动作'] }}</strong>
            <em>{{ log['操作人'] }}</em>
            <span v-if="log['说明']" class="log-note">：{{ log['说明'] }}</span>
          </li>
        </ul>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'
import StaffSwitcher from './StaffSwitcher.vue'
import { acceptComplaint, COMPLAINT_TYPES, loadMeta, runAction, STAGES } from './shared'

type Row = Record<string, unknown>
type DetailRow = Row & {
  '工单编号': string
  '责任班组': string
  status: string
  id: number
  '追加来电'?: CallRecord[]
  '操作流水'?: LogRecord[]
  '历史处置结论'?: string | null
  '归属补录'?: boolean
}
type CallRecord = { '序号': number; '来电时间': string; '反映内容': string; '受理人': string }
type LogRecord = { '时间': string; '环节': string; '动作': string; '操作人': string; '说明': string }

const store = useSessionStore()
const stageLabels = STAGES
const types = COMPLAINT_TYPES
const crews = ['无线班组', '资费班组']

const rows = ref<Row[]>([])
const total = ref(0)
const stages = ref(STAGES.map((label) => ({ label, value: 0 })))
const filters = reactive({ keyword: '', status: '', crew: '', ctype: '' })
const notice = ref<{ ok: boolean; text: string } | null>(null)

const accepting = ref(false)
const submitting = ref(false)
const acceptForm = reactive({ number: '', ctype: '', content: '' })

const modalAction = ref('')
const modalRow = ref<Row | null>(null)
const modalText = ref('')
const detail = ref<DetailRow | null>(null)

function crewOf(t: string) {
  return t === '资费' ? '资费班组' : '无线班组'
}
function stageClass(status: unknown) {
  return {
    's-0': status === '待处置',
    's-1': status === '处置中',
    's-2': status === '待回访',
    's-3': status === '已归档',
  }
}
function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  filters.crew = ''
  filters.ctype = ''
  void reload()
}

async function reload() {
  notice.value = null
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => v && params.set(k, v))
  params.set('operator_id', store.activeStaffId)
  try {
    const resp = await request(`/api/complaint?${params.toString()}`)
    if (!resp.ok) throw new Error('投诉工单列表读取失败')
    const payload = await resp.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? 0
  } catch (error) {
    notice.value = { ok: false, text: error instanceof Error ? error.message : '列表读取失败' }
  }
  try {
    const resp = await request('/api/complaint/stages')
    const payload = await resp.json()
    stages.value = payload.stages
  } catch {
    /* 看板计数失败不阻断列表 */
  }
}

function openAccept() {
  acceptForm.number = ''
  acceptForm.ctype = ''
  acceptForm.content = ''
  accepting.value = true
}

async function submitAccept() {
  notice.value = null
  submitting.value = true
  try {
    const result = await acceptComplaint({
      来电号码: acceptForm.number,
      投诉类型: acceptForm.ctype,
      反映内容: acceptForm.content,
    })
    notice.value = { ok: result.ok, text: result.message }
    if (result.ok) accepting.value = false
  } catch (error) {
    notice.value = { ok: false, text: error instanceof Error ? error.message : '受理失败' }
  } finally {
    submitting.value = false
    void reload()
  }
}

function openAction(action: string, row: Row) {
  modalAction.value = action
  modalRow.value = row
  modalText.value = ''
}

async function submitAction() {
  if (!modalRow.value) return
  notice.value = null
  const id = Number(modalRow.value.id)
  const payload: Record<string, unknown> = { action: modalAction.value }
  if (modalAction.value === '填写处置结论') payload['处置结论'] = modalText.value
  if (modalAction.value === '回访归档') payload['回访结论'] = modalText.value
  submitting.value = true
  try {
    const result = await runAction(id, payload)
    notice.value = { ok: result.ok, text: result.message }
    if (result.ok) modalAction.value = ''
  } catch (error) {
    notice.value = { ok: false, text: error instanceof Error ? error.message : '操作失败' }
  } finally {
    submitting.value = false
    void reload()
  }
}

async function openDetail(row: Row) {
  try {
    const resp = await request(`/api/complaint/${row.id}?operator_id=${store.activeStaffId}`)
    if (!resp.ok) throw new Error('工单明细读取失败')
    detail.value = await resp.json()
  } catch (error) {
    notice.value = { ok: false, text: error instanceof Error ? error.message : '明细读取失败' }
  }
}

async function runBackfill() {
  notice.value = null
  try {
    const resp = await request('/api/complaint/backfill', { method: 'POST', body: JSON.stringify({}) })
    const result = await resp.json()
    notice.value = { ok: result.ok, text: result.message }
    await loadMeta()
  } catch (error) {
    notice.value = { ok: false, text: error instanceof Error ? error.message : '存量补录失败' }
  }
  void reload()
}

onMounted(async () => {
  await loadMeta()
  await reload()
})
</script>

<style scoped>
.backfill-tip {
  font-size: 12px;
  color: #475467;
  background: #fffbeb;
  border: 1px solid #f5d28a;
  border-radius: 6px;
  padding: 6px 10px;
  margin-bottom: 12px;
}
.notice {
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 13px;
  margin-bottom: 10px;
}
.notice.ok { background: #ecfdf3; border: 1px solid #86efac; color: #166534; }
.notice.bad { background: #fef2f2; border: 1px solid #fca5a5; color: #991b1b; }
.tag { display: inline-block; font-size: 11px; border-radius: 4px; padding: 0 5px; margin-left: 4px; vertical-align: middle; }
.tag.legacy { background: #e2e8f0; color: #334155; }
.tag.backfill { background: #fef9c3; color: #854d0e; }
.tag.merge { background: #dbeafe; color: #1d4ed8; }
.stage { border-radius: 4px; padding: 1px 8px; font-size: 12px; }
.stage.s-0 { background: #e0e7ff; color: #3730a3; }
.stage.s-1 { background: #fef3c7; color: #92400e; }
.stage.s-2 { background: #ffe4e6; color: #9f1239; }
.stage.s-3 { background: #dcfce7; color: #166534; }
.cell-clip { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.muted-link { color: var(--muted); }
.readonly-hint { color: #94a3b8; font-size: 12px; margin-left: 6px; }
.modal-mask {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45);
  display: flex; align-items: center; justify-content: center; z-index: 50;
}
.modal {
  background: #fff; border-radius: 10px; padding: 18px 20px; width: 460px;
  max-height: 86vh; overflow: auto; box-shadow: 0 18px 50px rgba(0, 0, 0, 0.25);
}
.modal.wide { width: 680px; }
.modal h3 { margin: 0 0 6px; }
.modal h4 { margin: 14px 0 6px; font-size: 14px; }
.modal-tip { font-size: 12px; color: var(--muted); margin: 0 0 10px; }
.form-item { display: block; margin-bottom: 10px; }
.form-item span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 3px; }
.form-item input, .form-item select, .form-item textarea { width: 100%; padding: 6px 8px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.history-box { background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 6px; padding: 8px 10px; font-size: 13px; }
.data-table.sub th, .data-table.sub td { padding: 5px 8px; font-size: 12px; }
.empty-inline { color: var(--muted); font-size: 12px; }
.timeline { list-style: none; margin: 0; padding: 0; font-size: 13px; }
.timeline li { padding: 5px 0; border-bottom: 1px dashed #e5e7eb; }
.log-time { color: var(--muted); margin-right: 6px; }
.log-stage { color: #1f6feb; margin-right: 6px; }
.timeline em { font-style: normal; color: #475467; margin: 0 6px; }
.log-note { color: #475467; }
</style>
