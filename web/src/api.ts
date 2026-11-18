export interface Account { id: number; username: string; admin: boolean; roles: number[] }
export interface Role { id: number; name: string }
export interface Token { id: string; name: string; createdAt: string }
export interface Skill {
  slug: string
  name: string
  description: string
  status?: 'draft' | 'modified' | 'published' | 'archived'
}
export interface Release extends Skill { version: string; releasedAt: string }
export interface ReleaseContent extends Release { source: string; files: string[] }
export interface Draft {
  skill: Skill
  source: string
  files: string[]
  roles: number[]
  releases: Release[]
  nextVersion: string
}

export class ApiError extends Error {
  constructor(readonly status: number, message: string) { super(message) }
}

export async function api<T>(path: string, method = 'GET', body?: object): Promise<T> {
  const headers: Record<string, string> = { 'X-Skill-Inventory': '1' }
  if (body && !(body instanceof FormData)) headers['Content-Type'] = 'application/json'
  const response = await fetch('/api/v1' + path, {
    method, headers, body: body instanceof FormData ? body : body && JSON.stringify(body),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new ApiError(response.status, error?.message ?? `请求失败（${response.status}）`)
  }
  if (response.status === 204 || !response.headers.get('Content-Type')?.includes('application/json')) {
    return undefined as T
  }
  return response.json() as Promise<T>
}
