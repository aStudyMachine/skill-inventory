<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, type Token } from './api'

const tokens = ref<Token[]>([])
const name = ref('')
const newToken = ref('')
const error = ref('')
const notice = ref('')
const busy = ref(false)

async function run(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try { await action(); tokens.value = await api<Token[]>('/device-tokens') }
  catch (e) { error.value = (e as Error).message }
  finally { busy.value = false }
}

onMounted(() => run(async () => {}))

const issue = () => run(async () => {
  const result = await api<Token & { token: string }>('/device-tokens', 'POST', { name: name.value })
  newToken.value = result.token
  notice.value = ''
  name.value = ''
})

function revoke(id: string) {
  if (!window.confirm('撤销此设备令牌？设备将无法继续使用它同步。')) return
  return run(async () => { await api('/device-tokens/' + id, 'DELETE'); newToken.value = '' })
}

async function copy() {
  try { await navigator.clipboard.writeText(newToken.value); notice.value = '已复制' }
  catch { notice.value = '无法写入剪贴板，请手动复制。' }
}
</script>

<template>
  <div class="page-heading"><h1>设备令牌</h1></div>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <section class="card">
    <form @submit.prevent="issue">
      <label>设备名称<input v-model="name" maxlength="80" required /></label>
      <button class="primary" :disabled="busy">签发令牌</button>
    </form>
    <div v-if="newToken" class="section">
      <label>令牌仅显示一次<input :value="newToken" readonly autocomplete="off" /></label>
      <button @click="copy">复制令牌</button>
      <button @click="newToken = ''">关闭</button>
      <span v-if="notice" role="status">{{ notice }}</span>
    </div>
    <div class="section">
      <h2>已签发令牌</h2>
      <p v-if="!tokens.length" class="muted">暂无令牌</p>
      <div v-for="token in tokens" :key="token.id" class="toolbar">
        <span>{{ token.name }} <small>{{ new Date(token.createdAt).toLocaleString() }}</small></span>
        <button class="danger" :disabled="busy" @click="revoke(token.id)">撤销</button>
      </div>
    </div>
  </section>
</template>
