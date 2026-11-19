<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, type Account, type Role } from './api'

const accounts = ref<Account[]>([])
const roles = ref<Role[]>([])
const username = ref('')
const password = ref('')
const roleName = ref('')
const error = ref('')
const notice = ref('')
const busy = ref(false)

async function refresh() {
  ;[accounts.value, roles.value] = await Promise.all([
    api<Account[]>('/admin/accounts'), api<Role[]>('/admin/roles'),
  ])
}

async function run(action: () => Promise<void>, message = '') {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try { await action(); notice.value = message }
  catch (e) { error.value = (e as Error).message }
  finally { busy.value = false }
}

onMounted(() => run(refresh))

const createAccount = () => run(async () => {
  try {
    await api('/admin/accounts', 'POST', { username: username.value, password: password.value })
    username.value = ''
    await refresh()
  } finally { password.value = '' }
}, '账号已创建')

const createRole = () => run(async () => {
  await api('/admin/roles', 'POST', { name: roleName.value })
  roleName.value = ''
  await refresh()
}, '角色已创建')

const assign = (account: Account) => run(async () => {
  await api('/admin/accounts/' + account.id + '/roles', 'PUT', { ids: account.roles })
}, '角色分配已保存')
const changeStatus = (account: Account) => run(async () => {
  if (account.enabled && !window.confirm('停用后，此账号的所有登录会话都会失效。继续？')) return
  await api('/admin/accounts/' + account.id + '/status', 'PUT', { enabled: !account.enabled })
  await refresh()
})

const newPasswords = ref<Record<number, string>>({})
const changePassword = (account: Account) => run(async () => {
  try {
    await api('/admin/accounts/' + account.id + '/password', 'PUT', { password: newPasswords.value[account.id] })
  } finally { delete newPasswords.value[account.id] }
}, '密码已修改，原登录会话已失效')
</script>

<template>
  <div class="page-heading"><h1>账号与角色</h1></div>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <p v-if="notice" class="notice" role="status">{{ notice }}</p>
  <div class="columns">
    <form class="card" @submit.prevent="createAccount">
      <h2>新建普通账号</h2>
      <label>账号<input v-model="username" required autocomplete="off" maxlength="64" /></label>
      <label>密码<input v-model="password" required type="password" autocomplete="new-password" minlength="10" /></label>
      <button class="primary" :disabled="busy">创建账号</button>
    </form>
    <form class="card" @submit.prevent="createRole">
      <h2>新建角色</h2>
      <label>角色名称<input v-model="roleName" required maxlength="64" /></label>
      <button class="primary" :disabled="busy">创建角色</button>
      <ul v-if="roles.length"><li v-for="role in roles" :key="role.id">{{ role.name }}</li></ul>
    </form>
  </div>
  <section class="card section">
    <h2>账号管理</h2>
    <div v-for="account in accounts" :key="account.id" class="section">
      <h3>{{ account.username }}</h3>
      <p v-if="account.admin" class="muted">管理员</p>
      <form v-else @submit.prevent="assign(account)">
        <p>{{ account.enabled ? '已启用' : '已停用' }}</p>
        <label v-for="role in roles" :key="role.id" class="check"><input v-model="account.roles" :value="role.id" type="checkbox" />{{ role.name }}</label>
        <button :disabled="busy">保存角色</button>
        <button type="button" :disabled="busy" @click="changeStatus(account)">{{ account.enabled ? '停用账号' : '启用账号' }}</button>
      </form>
      <form @submit.prevent="changePassword(account)">
        <label>新密码<input v-model="newPasswords[account.id]" required minlength="10" type="password" autocomplete="new-password" /></label>
        <button :disabled="busy">修改密码</button>
      </form>
    </div>
  </section>
</template>
