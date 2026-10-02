import { defineStore } from 'pinia'

export type Staff = {
  工号: string
  姓名: string
  班组: string
  角色: string[]
}

type SessionState = {
  operator: string
  shiftLabel: string
  scope: string
  activeStaffId: string
  roster: Staff[]
  backfill: { legacy_total: number; missing_crew: number; backfilled: number } | null
}

export const useSessionStore = defineStore('session', {
  state: (): SessionState => ({
    operator: '值班管理员',
    shiftLabel: '白班 08:00-20:00',
    scope: '通信基站运维管理平台',
    // 当前值班身份：跨班组只读、越权驳回都按这个工号在后端校验。
    activeStaffId: 'C001',
    roster: [],
    backfill: null,
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
    activeStaff(state): Staff | undefined {
      return state.roster.find((item) => item.工号 === state.activeStaffId)
    },
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setActiveStaff(staffId: string) {
      this.activeStaffId = staffId
      const staff = this.roster.find((item) => item.工号 === staffId)
      if (staff) {
        this.operator = staff.姓名
      }
    },
    setMeta(meta: { roster: Staff[]; backfill: SessionState['backfill'] }) {
      this.roster = meta.roster
      this.backfill = meta.backfill
      if (!this.roster.some((item) => item.工号 === this.activeStaffId) && this.roster.length) {
        this.setActiveStaff(this.roster[0].工号)
      }
    },
  },
})
