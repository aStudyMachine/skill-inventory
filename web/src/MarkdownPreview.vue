<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed } from 'vue'

const props = defineProps<{ source: string }>()
const preview = computed(() => {
  const markdown = props.source.replace(/^---\r?\n[\s\S]*?\r?\n---(?:\r?\n|$)/, '')
  return DOMPurify.sanitize(marked.parse(markdown, { async: false }), {
    ALLOWED_TAGS: ['a', 'p', 'blockquote', 'pre', 'code', 'em', 'strong', 'del', 'ul', 'ol', 'li',
      'hr', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'thead', 'tbody', 'tr', 'th', 'td'],
    ALLOWED_ATTR: ['href', 'title', 'start'],
    ALLOW_DATA_ATTR: false,
  })
})
</script>

<template><article class="markdown" v-html="preview"></article></template>
