<template>
  <div class="staff-bar">
    <label class="staff-pick">
      <span>当前值班身份（越权操作将被后端驳回）</span>
      <select :value="store.activeStaffId" @change="onChange">
        <option v-for="s in store.roster" :key="s.工号" :value="s.工号">
          {{ s.姓名 }} · {{ s.班组 }} · {{ s.角色.join('/') }}
        </option>
      </select>
    </label>
    <span v-if="store.activeStaff" class="staff-meta">
      工号 {{ store.activeStaff.工号 }}，所属{{ store.activeStaff.班组 }}
    </span>
  </div>
</template>

<script setup lang="ts">
import { useSessionStore } from '@/stores/session'

const store = useSessionStore()

function onChange(event: Event) {
  store.setActiveStaff((event.target as HTMLSelectElement).value)
}
</script>

<style scoped>
.staff-bar {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  background: #eef4ff;
  border: 1px solid #c7d9f7;
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 12px;
}
.staff-pick span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 2px;
}
.staff-pick select {
  min-width: 260px;
  padding: 4px 8px;
}
.staff-meta {
  font-size: 12px;
  color: var(--muted);
}
</style>
