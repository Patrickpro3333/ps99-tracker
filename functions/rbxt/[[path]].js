import { proxy } from '../../cloudflare/proxy.js'

export const onRequest = ctx => proxy(ctx, 'rbxt')
