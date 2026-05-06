// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// Static site; deploy as Cloudflare Pages with `wrangler pages deploy dist`.
export default defineConfig({
	site: 'https://quant.panda.qzz.io',
	base: '/docs',
	trailingSlash: 'always',
	build: { format: 'directory' },
	integrations: [
		starlight({
			title: 'Crypto Quant Docs',
			description: 'Documentation for the quant trading system',
			social: [
				{
					icon: 'github',
					label: 'GitHub',
					href: 'https://github.com/xiongchenyu6/freqtrade-strategies'
				}
			],
			defaultLocale: 'root',
			locales: {
				root: { label: '简体中文', lang: 'zh-CN' },
				en: { label: 'English', lang: 'en' }
			},
			customCss: ['./src/styles/custom.css'],
			head: [
				{
					tag: 'link',
					attrs: { rel: 'preconnect', href: 'https://rsms.me' }
				},
				{
					tag: 'link',
					attrs: { rel: 'stylesheet', href: 'https://rsms.me/inter/inter.css' }
				},
				// Sync the app's `lang` cookie to the current Starlight URL locale.
				// This makes the app topbar pick up the matching language next time
				// the user navigates to a non-docs route.
				{
					tag: 'script',
					content:
						"(function(){var l=location.pathname.indexOf('/docs/en/')===0?'en':'zh';document.cookie='lang='+l+'; path=/; max-age=31536000; SameSite=Lax';})();"
				}
			],
			sidebar: [
				{
					label: '← 返回 Dashboard',
					translations: { en: '← Back to Dashboard' },
					link: '/',
					attrs: { target: '_self' }
				},
				{
					label: '起步',
					translations: { en: 'Getting started' },
					items: [
						{
							label: '架构总览',
							translations: { en: 'Architecture' },
							slug: 'architecture'
						}
					]
				},
				{
					label: '策略',
					translations: { en: 'Strategies' },
					collapsed: false,
					autogenerate: { directory: 'strategies' }
				},
				{
					label: '调优与实验',
					translations: { en: 'Tuning & research' },
					collapsed: true,
					autogenerate: { directory: 'research' }
				},
				{
					label: '运维',
					translations: { en: 'Operations' },
					collapsed: true,
					autogenerate: { directory: 'ops' }
				},
				{
					label: '历史 & 教训',
					translations: { en: 'History & lessons' },
					collapsed: true,
					autogenerate: { directory: 'history' }
				}
			]
		})
	]
});
