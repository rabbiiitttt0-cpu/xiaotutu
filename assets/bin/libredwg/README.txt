LibreDWG 二进制说明（GPL-3.0 合规）

本目录存放 GNU LibreDWG 的预编译命令行工具 dwg2dxf，用于将用户上传的
DWG 图纸转换为 DXF（作为独立外部进程被本系统调用，不构成衍生作品）。

- 上游项目: https://github.com/LibreDWG/libredwg （GNU 项目，GPL-3.0-or-later）
- 版本: 0.14.8597（2026-09-10 nightly pre-release）
- win/dwg2dxf.exe 及配套 DLL: 直接取自官方 release 包 libredwg-0.14.8597-win64.zip，未修改
- linux/dwg2dxf + libredwg.so.0: 由同版本源码 libredwg-0.14.8597.tar.xz 在
  Alibaba Cloud Linux 3 (OpenAnolis) 编译（strip 后：dwg2dxf 16K + libredwg.so.0 20M，
  动态链接，部署时 libredwg.so.0 放 /usr/local/lib 并 ldconfig）
- 源码获取: https://github.com/LibreDWG/libredwg/releases/tag/0.14.8597
  （GPL-3.0 要求的对应源码即上述官方发布 tarball）
- 许可证全文: https://www.gnu.org/licenses/gpl-3.0.txt

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License version 3 or later.
