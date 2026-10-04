// DXF 文本分析：编码判定 + 字体清单（喂给 dxf-viewer 的 fileEncoding 和陌生字体横幅）
//
// 背景：dxf-viewer 的 DxfFetcher 默认按 UTF-8 解码整个文件，但 LibreDWG(dwg2dxf)
// 对 ANSI_936 图纸输出的是 GBK 字节（云中心结构图0701 实测：文字实体里 1761 个中文
// 值行全为 GBK、0 个 UTF-8）→ UTF-8 强解出 U+FFFD → 字形查不到 → 满屏问号。
// 后端 ezdxf 按 $DWGCODEPAGE 解码，问答链路不受影响；此分析只服务前端预览。
//
// 字体清单必须从文件直扫，不能读 viewer.parsedDxf.tables.style：
//   - parser 的 STYLE 记录按组2(styleName) 做键，GBK 中文名被 UTF-8 强解后全变
//     同一串 U+FFFD → 互相覆盖（45 条记录只剩 3 条）；
//   - dwg2dxf 产物的组3/组4 字体名经常为空，经 viewer 读不可靠。
// 本模块按组码/值成对行扫描，latin1 无损读字节，两遍扫描（先判编码、再按最终
// 编码收集 STYLE 段字体），与后端 python 实扫对照：45 条 STYLE、30 种字体。
//
// 判定策略（$DWGCODEPAGE 头不可信：CS-2 图声明 ANSI_936 但文字实为 UTF-8）：
//   1) 整文件严格 UTF-8 解码成功 → utf-8（快速路径）；
//   2) 失败 → 扫 TEXT/MTEXT/ATTRIB/ATTDEF 实体的组码 1 值行，严格 UTF-8 / GBK
//      试解统计"解出真中文"的行数；
//   3) GBK 明显占多 → 'gbk'，否则 'utf-8'。

const CN_RE = /[一-鿿]/  // CJK 基本区
const TEXT_TYPES = new Set(['TEXT', 'MTEXT', 'ATTRIB', 'ATTDEF'])
const CODE_RE = /^-?\d+$/  // 组码行（文件头注释/空行的错位重同步用）

// 非 ASCII 行按指定编码解码为可读文本；解不动返回 null
function decodeLine(str, encoding) {
  if (!/[\x80-\xff]/.test(str)) return str
  const bytes = new Uint8Array(str.length)
  for (let j = 0; j < str.length; j++) bytes[j] = str.charCodeAt(j) & 0xff
  try {
    return new TextDecoder(encoding, encoding === 'utf-8' ? { fatal: true } : undefined).decode(bytes)
  } catch {
    return null
  }
}

// 找到第一个组码行并对齐到成对结构（DXF 组码/值严格成对）
function alignStart(lines) {
  let start = 0
  while (start < lines.length && !CODE_RE.test(lines[start].trim())) start++
  if (start > 0) start = start % 2 === 0 ? start : start - 1
  return Math.max(0, start)
}

/** 第一遍：判定编码（只看文字实体组1 的中文统计） */
function detectEncoding(lines) {
  try {
    // 快速路径在调用方已完成；这里仅统计文字实体
    const utf8dec = new TextDecoder('utf-8', { fatal: true })
    const gbkdec = new TextDecoder('gbk')
    let utf8cn = 0
    let gbkcn = 0
    let inText = false
    for (let k = alignStart(lines); k + 1 < lines.length; k += 2) {
      const code = lines[k].trim()
      const val = lines[k + 1]
      if (code === '0') { inText = TEXT_TYPES.has(val.trim()); continue }
      if (!inText || code !== '1') continue
      if (!/[\x80-\xff]/.test(val)) continue
      const bytes = new Uint8Array(val.length)
      for (let j = 0; j < val.length; j++) bytes[j] = val.charCodeAt(j) & 0xff
      try {
        if (CN_RE.test(utf8dec.decode(bytes))) utf8cn++
      } catch {
        try {
          if (CN_RE.test(gbkdec.decode(bytes))) gbkcn++
        } catch { /* 两种都解不出的脏值行，忽略 */ }
      }
    }
    // GBK 中文行显著更多才判 gbk（阈值防个别脏行误伤 UTF-8 文件）
    return (gbkcn >= 10 && gbkcn > utf8cn) ? 'gbk' : 'utf-8'
  } catch {
    return 'utf-8'
  }
}

/** 第二遍：按最终编码收集 STYLE 段组3/组4/1071 引用的字体名（段边界用 inStyle 跟踪） */
function collectFonts(lines, encoding) {
  const fonts = new Set()
  let inStyle = false
  for (let k = alignStart(lines); k + 1 < lines.length; k += 2) {
    const code = lines[k].trim()
    const val = lines[k + 1]
    if (code === '0') { inStyle = val.trim() === 'STYLE'; continue }
    if (!inStyle) continue
    // 组3=primary字体 组4=SHX大字体；1071 是数字型 flag 不是字体名，勿收
    if (code === '3' || code === '4') {
      const name = decodeLine(val, encoding)
      if (name && name.trim()) fonts.add(name.trim())
    }
  }
  return [...fonts]
}

/**
 * 扫描 DXF 文件，返回 { encoding: 'utf-8'|'gbk', fonts: string[] }
 */
export async function analyzeDxfFile(blob) {
  try {
    const buf = await blob.arrayBuffer()
    // 快速路径：整文件就是合法 UTF-8 → 文字无需再判（字体仍要扫）
    let isStrictUtf8 = true
    try {
      new TextDecoder('utf-8', { fatal: true }).decode(buf)
    } catch {
      isStrictUtf8 = false
    }

    // latin1 逐字节映射（标签必须是 latin1/iso-8859-1；'latin-1' 不是合法标签会抛 RangeError）
    const raw = new TextDecoder('latin1').decode(buf)
    const lines = raw.split(/\r?\n/)

    const encoding = isStrictUtf8 ? 'utf-8' : detectEncoding(lines)
    const fonts = collectFonts(lines, encoding)
    return { encoding, fonts }
  } catch {
    return { encoding: 'utf-8', fonts: [] }  // 分析异常按默认走，最坏退回现状
  }
}
