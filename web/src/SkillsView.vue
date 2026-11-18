<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, type Draft, type Release, type ReleaseContent, type Role, type Skill } from './api'
import MarkdownPreview from './MarkdownPreview.vue'

const props = defineProps<{admin: boolean}>()
const statuses = { draft: '未发布', published: '已发布', modified: '有未发布修改', archived: '已归档' }
const list = ref<(Skill | Release)[]>([])
const roles = ref<Role[]>([])
const query = ref('')
const draft = ref<Draft>()
const release = ref<ReleaseContent>()
const releases = ref<Release[]>([])
const version = ref('')
const selectedRoles = ref<number[]>([])
const creating = ref(false)
const preview = ref(false)
const starter = (slug: string) => '---\nname: ' + slug + '\ndescription: 技能用途\n---\n\n# 使用方法\n'
const editor = ref({ slug: '', name: '', description: '', source: '' })
const dirty = computed(() => !!draft.value && (
  editor.value.name !== draft.value.skill.name || editor.value.description !== draft.value.skill.description ||
  editor.value.source !== draft.value.source))
const error = ref('')
const notice = ref('')
const busy = ref(false)
const filtered = computed(() => {
  const term = query.value.trim().toLowerCase()
  return list.value.filter(skill => skill.name.toLowerCase().includes(term) || skill.slug.includes(term))
})
const adminPath = (slug = '') => '/admin/skills' + (slug ? '/' + slug : '')
const readPath = (slug: string) => '/skills/' + slug
const packagePath = computed(() => {
  const item = release.value
  if (!item) return ''
  return '/api/v1' + (props.admin ? adminPath(item.slug) + '/releases/' + item.version + '/package' :
    readPath(item.slug) + '/package?version=' + item.version)
})

async function run(action: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try { await action() }
  catch (e) { error.value = (e as Error).message }
  finally { busy.value = false }
}

async function refresh() {
  list.value = await api<(Skill | Release)[]>(props.admin ? adminPath() : '/skills')
}

onMounted(() => run(async () => {
  await refresh()
  if (props.admin) roles.value = await api<Role[]>('/admin/roles')
}))

async function loadDraft(slug: string) {
  const result = await api<Draft>(adminPath(slug))
  draft.value = result
  editor.value = { slug, name: result.skill.name, description: result.skill.description, source: result.source }
  selectedRoles.value = [...result.roles]
  version.value = result.nextVersion
  creating.value = false
  release.value = undefined
  preview.value = false
}

function canLeave() {
  const input = editor.value
  const changedNew = creating.value && (input.slug || input.name || input.description || input.source !== starter(''))
  return !busy.value && (!(dirty.value || changedNew) || window.confirm('放弃当前表单中的修改？'))
}

defineExpose({ canLeave })

function open(skill: Skill) {
  if (!canLeave()) return
  return run(async () => {
    if (props.admin) await loadDraft(skill.slug)
    else {
      releases.value = await api<Release[]>(readPath(skill.slug) + '/versions')
      await openRelease(skill.slug, releases.value[0]?.version ?? '')
    }
  })
}

function newSkill() {
  if (!canLeave()) return
  draft.value = undefined
  release.value = undefined
  preview.value = false
  creating.value = true
  editor.value = { slug: '', name: '', description: '', source: starter('') }
}

async function save() {
  await run(async () => {
    const slug = editor.value.slug
    const input = { ...editor.value }
    if (creating.value) input.source = input.source.replace(/^---\nname: \n/, '---\nname: ' + slug + '\n')
    await api(creating.value ? adminPath() : adminPath(slug), creating.value ? 'POST' : 'PUT', input)
    await loadDraft(slug)
    await refresh()
    notice.value = '草稿已保存'
  })
}

async function importZip(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !draft.value || !window.confirm('用 ZIP 替换整个草稿文件包？')) return
  const slug = draft.value.skill.slug
  await run(async () => {
    const form = new FormData()
    form.append('file', file)
    await api(adminPath(slug) + '/package', 'PUT', form)
    const selection = selectedRoles.value
    await loadDraft(slug)
    selectedRoles.value = selection
    await refresh()
    notice.value = '文件包已导入草稿'
  })
}

async function publish() {
  const slug = editor.value.slug
  await run(async () => {
    await api(adminPath(slug) + '/releases', 'POST', { version: version.value })
    await loadDraft(slug)
    await refresh()
    notice.value = '版本已发布'
  })
}

async function remove() {
  const slug = editor.value.slug
  if (!window.confirm(draft.value?.skill.status === 'draft' ? '删除这个未发布的草稿？' : '归档后将停止分发所有版本。继续归档？')) return
  await run(async () => {
    await api(adminPath(slug), 'DELETE')
    draft.value = undefined
    release.value = undefined
    await refresh()
  })
}

async function grant() {
  await run(async () => {
    if (!draft.value) return
    await api(adminPath(draft.value.skill.slug) + '/roles', 'PUT', { ids: selectedRoles.value })
    notice.value = '角色授权已保存'
  })
}

async function openRelease(slug: string, chosen: string) {
  if (props.admin) {
    release.value = await api<ReleaseContent>(adminPath(slug) + '/releases/' + chosen)
  } else {
    const info = await api<ReleaseContent>(readPath(slug) + '?version=' + chosen)
    const response = await fetch('/api/v1' + readPath(slug) + '/content?version=' + chosen)
    if (!response.ok) throw new Error('无法读取该版本正文')
    release.value = { ...info, source: await response.text() }
  }
}
</script>

<template>
  <div class="page-heading">
    <h1>Skill 库</h1>
    <button v-if="admin" class="primary" :disabled="busy" @click="newSkill">新建 Skill</button>
  </div>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <p v-if="notice" class="notice" role="status">{{ notice }}</p>
  <div class="layout">
    <aside class="card inventory-list">
      <label>搜索<input v-model="query" placeholder="名称或 slug" type="search" /></label>
      <p v-if="!filtered.length" class="muted">没有匹配的 Skill</p>
      <button v-for="skill in filtered" :key="skill.slug" class="skill-row" type="button"
        :class="{ selected: draft?.skill.slug === skill.slug || release?.slug === skill.slug }"
        :disabled="busy" @click="open(skill)">
        <span><strong>{{ skill.name }}</strong><small>{{ skill.slug }}</small></span>
        <small v-if="skill.status">{{ statuses[skill.status] }}</small>
        <small v-else-if="'version' in skill">{{ skill.version }}</small>
      </button>
    </aside>
    <section v-if="admin && (creating || draft)" class="card">
      <h2>{{ creating ? '新建 Skill' : draft?.skill.name }}</h2>
      <form @submit.prevent="save">
        <div class="columns">
          <label>slug<input v-model="editor.slug" :disabled="!creating" required pattern="[a-z0-9]+(-[a-z0-9]+)*" maxlength="64" /></label>
          <label>显示名称<input v-model="editor.name" :disabled="draft?.skill.status === 'archived'" required maxlength="128" /></label>
        </div>
        <label>描述<input v-model="editor.description" :disabled="draft?.skill.status === 'archived'" maxlength="1024" /></label>
        <div class="toolbar"><strong>SKILL.md</strong><button type="button" @click="preview = !preview">{{ preview ? '编辑' : 'Markdown 预览' }}</button></div>
        <MarkdownPreview v-if="preview" :source="editor.source" />
        <textarea v-else v-model="editor.source" aria-label="SKILL.md" :readonly="draft?.skill.status === 'archived'" rows="12"></textarea>
        <button v-if="draft?.skill.status !== 'archived'" class="primary" :disabled="busy">保存草稿</button>
      </form>
      <template v-if="draft">
        <details open>
          <summary>文件清单</summary>
          <ul><li v-for="file in draft.files" :key="file"><code>{{ file }}</code></li></ul>
          <label v-if="draft.skill.status !== 'archived'">导入或替换 ZIP<input type="file" accept=".zip,application/zip" :disabled="busy || dirty" @change="importZip" /></label>
        </details>
        <template v-if="draft.skill.status !== 'archived'">
          <form class="section" @submit.prevent="grant">
            <h3>角色授权</h3>
            <p v-if="!roles.length" class="muted">请在账号与角色中创建可授权的角色。</p>
            <label v-for="role in roles" :key="role.id" class="check"><input v-model="selectedRoles" type="checkbox" :value="role.id" />{{ role.name }}</label>
            <button :disabled="busy">保存授权</button>
          </form>
          <form class="section" @submit.prevent="publish">
            <label>发布版本<input v-model="version" required placeholder="1.0.0" /></label>
            <button class="primary" :disabled="busy || dirty">发布</button>
            <small v-if="dirty">请先保存草稿。</small>
          </form>
        </template>
        <details open>
          <summary>发布历史</summary>
          <p v-if="!draft.releases.length" class="muted">暂无发布版本</p>
          <button v-for="item in draft.releases" :key="item.version" type="button"
            @click="run(() => openRelease(editor.slug, item.version))">{{ item.version }}</button>
        </details>
        <button v-if="draft.skill.status !== 'archived'" class="danger section" :disabled="busy" @click="remove">
          {{ draft.skill.status === 'draft' ? '删除草稿' : '归档 Skill' }}
        </button>
      </template>
      <div v-if="release" class="section">
        <div class="toolbar"><h3>发布版本 {{ release.version }}</h3><a :href="packagePath">下载 ZIP</a></div>
        <MarkdownPreview :source="release.source" />
      </div>
    </section>
    <section v-else-if="release" class="card">
      <h2>{{ release.name }}</h2><p>{{ release.description }}</p>
      <div class="toolbar">
        <label>发布版本
          <select :value="release.version" :disabled="busy"
            @change="run(() => openRelease(release!.slug, ($event.target as HTMLSelectElement).value))">
            <option v-for="item in releases" :key="item.version">{{ item.version }}</option>
          </select>
        </label>
        <a :href="packagePath">下载 ZIP</a>
      </div>
      <MarkdownPreview :source="release.source" />
      <details><summary>文件清单</summary><ul><li v-for="file in release.files" :key="file"><code>{{ file }}</code></li></ul></details>
    </section>
    <section v-else class="card empty">从列表中选择一个 Skill。</section>
  </div>
</template>
