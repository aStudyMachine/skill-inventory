<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, ApiError, type Account } from './api'
import SkillsView from './SkillsView.vue'
import AccessView from './AccessView.vue'

const account = ref<Account>()
const panel = ref('skills')
const skills = ref<InstanceType<typeof SkillsView>>()
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(true)

onMounted(async () => {
  try { account.value = await api<Account>('/session') }
  catch (e) { if (!(e instanceof ApiError && e.status === 401)) error.value = String(e) }
  finally { loading.value = false }
})

async function login() {
  loading.value = true
  error.value = ''
  try { account.value = await api<Account>('/session', 'POST', { username: username.value, password: password.value }) }
  catch (e) { error.value = (e as Error).message }
  finally { loading.value = false; password.value = '' }
}

async function logout() {
  if (skills.value && !skills.value.canLeave()) return
  try {
    await api('/session', 'DELETE')
    account.value = undefined
    panel.value = 'skills'
  } catch (e) { error.value = (e as Error).message }
}

function navigate(destination: string) {
  if (panel.value !== destination && (!skills.value || skills.value.canLeave())) panel.value = destination
}
</script>

<template>
  <header class="topbar">
    <div class="brand"><span class="brand-icon" aria-hidden="true">SI</span> Skill Inventory</div>
    <template v-if="account">
      <nav aria-label="主导航">
        <button :aria-current="panel === 'skills' ? 'page' : undefined" @click="navigate('skills')">Skill 库</button>
        <button v-if="account.admin" :aria-current="panel === 'access' ? 'page' : undefined" @click="navigate('access')">账号与角色</button>
      </nav>
      <div class="identity"><span>{{ account.username }}</span><button @click="logout">退出</button></div>
    </template>
  </header>
  <main>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <template v-if="account">
      <SkillsView v-if="panel === 'skills'" ref="skills" :admin="account.admin" />
      <AccessView v-else-if="panel === 'access' && account.admin" />
    </template>
    <form v-else class="login card" @submit.prevent="login">
      <h1>登录</h1>
      <label>账号<input v-model="username" autocomplete="username" required /></label>
      <label>密码<input v-model="password" autocomplete="current-password" type="password" required /></label>
      <button class="primary" :disabled="loading">登录</button>
    </form>
  </main>
</template>
