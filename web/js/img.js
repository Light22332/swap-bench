/* 图片地址：原图是几 MB 的 PNG，页面上只显示几百像素宽。
   /img 支持 ?w=宽度&fmt=webp 现压一份并缓存，所以显示统一走这里；
   保存/下载仍然用原图地址，画质不动。 */

/** 把 /img?path=… 变成带宽度与格式的地址；别的地址原样返回。 */
export function thumb(url, width, fmt = 'webp') {
  if (!url || !url.startsWith('/img?')) return url || '';
  return url + '&w=' + width + '&fmt=' + fmt;
}

/** 给 <img srcset> 用：同一张图出几个宽度，让浏览器按屏幕挑。 */
export function srcset(url, widths) {
  if (!url || !url.startsWith('/img?')) return '';
  return widths.map((w) => thumb(url, w) + ' ' + w + 'w').join(', ');
}
