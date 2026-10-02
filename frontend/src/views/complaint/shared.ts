/** 客户投诉工单共享逻辑：值班身份、环节口径、动作回传都集中在这里。 */
import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

export const STAGES = ['待处置', '处置中', '待回访', '已归档']
export const COMPLAINT_TYPES = ['断站', '掉话', '资费']

export type ActionResult = {
  ok: boolean
  message: string
  entry?: Record<string, unknown>
}

export async function loadMeta(): Promise<void> {
  const store = useSessionStore()
  const resp = await request('/api/complaint/meta')
  if (!resp.ok) throw new Error('投诉基础数据读取失败')
  const meta = await resp.json()
  store.setMeta(meta)
}

export async function runAction(id: number, values: Record<string, unknown>): Promise<ActionResult> {
  const store = useSessionStore()
  const resp = await request(`/api/complaint/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ values: { operator_id: store.activeStaffId, ...values } }),
  })
  if (!resp.ok) throw new Error('投诉工单动作未送达，请稍后重试')
  return (await resp.json()) as ActionResult
}

export async function acceptComplaint(values: Record<string, unknown>): Promise<ActionResult> {
  const store = useSessionStore()
  const resp = await request('/api/complaint', {
    method: 'POST',
    body: JSON.stringify({ values: { operator_id: store.activeStaffId, ...values } }),
  })
  if (!resp.ok) throw new Error('投诉受理未送达，请稍后重试')
  return (await resp.json()) as ActionResult
}
