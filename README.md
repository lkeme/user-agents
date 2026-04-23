# User-Agent

## 数据

| 平台          | 浏览器     | 全部记录 (JSON)                                           | 最新 50 条记录 (JSON)                                                |
|-------------|---------|-------------------------------------------------------|-----------------------------------------------------------------|
| **全部**      | -       | [all.json](./output/all.json)                         | [all_latest50.json](./output/all_latest50.json)                 |
| **当前**      | -       | [current.json](./output/current.json)                 | -                                                               |
| **Windows** | Chrome  | [chrome_all.json](./output/Windows/chrome_all.json)   | [chrome_latest50.json](./output/Windows/chrome_latest50.json)   |
|             | Firefox | [firefox_all.json](./output/Windows/firefox_all.json) | [firefox_latest50.json](./output/Windows/firefox_latest50.json) |
|             | Edge    | [edge_all.json](./output/Windows/edge_all.json)       | [edge_latest50.json](./output/Windows/edge_latest50.json)       |
| **Mac**     | Chrome  | [chrome_all.json](./output/Mac/chrome_all.json)       | [chrome_latest50.json](./output/Mac/chrome_latest50.json)       |
|             | Firefox | [firefox_all.json](./output/Mac/firefox_all.json)     | [firefox_latest50.json](./output/Mac/firefox_latest50.json)     |
|             | Safari  | [safari_all.json](./output/Mac/safari_all.json)       | [safari_latest50.json](./output/Mac/safari_latest50.json)       |
| **Linux**   | Chrome  | [chrome_all.json](./output/Linux/chrome_all.json)     | [chrome_latest50.json](./output/Linux/chrome_latest50.json)     |
|             | Firefox | [firefox_all.json](./output/Linux/firefox_all.json)   | [firefox_latest50.json](./output/Linux/firefox_latest50.json)   |

## 关于

当前脚本直接从官方数据源生成桌面浏览器 User-Agent，并在本仓库保存历史快照。

- Chrome: `versionhistory.googleapis.com`
- Firefox: `product-details.mozilla.org/1.0/firefox_versions.json`
- Safari: Apple Safari Release Notes JSON
- Edge: `edgeupdates.microsoft.com/api/products`

本项目参考了 [jnrbsn/user-agents](https://github.com/jnrbsn/user-agents) 的生成思路，但不再依赖其 Actions 产物。
