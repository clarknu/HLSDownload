// 内容脚本 - 在页面中运行，补充网络监控
console.log('M3U8 Monitor: 内容脚本已注入');

// 发送页面信息到后台脚本
function sendPageInfo() {
  chrome.runtime.sendMessage({
    type: 'PAGE_INFO',
    url: window.location.href,
    title: document.title,
    referrer: document.referrer,
    timestamp: Date.now()
  }).catch(() => {}); // 忽略错误
}

// 页面加载时发送信息
sendPageInfo();

// 监听页面变化
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', sendPageInfo);
} else {
  sendPageInfo();
}

// 检查内容是否为真正的M3U8文件
function isValidM3U8Content(content) {
  if (!content || typeof content !== 'string') return false;
  
  const contentUpper = content.toUpperCase();
  
  // M3U8文件必须以#EXTM3U开头
  if (!contentUpper.startsWith('#EXTM3U')) return false;
  
  // 检查关键的M3U8标签
  const requiredTags = [
    '#EXT-X-VERSION',
    '#EXT-X-TARGETDURATION', 
    '#EXTINF',
    '#EXT-X-STREAM-INF',
    '#EXT-X-MEDIA'
  ];
  
  // 至少包含一个必要标签
  return requiredTags.some(tag => contentUpper.includes(tag));
}

// 检查URL是否为M3U8相关
function isM3U8Url(url) {
  if (!url || typeof url !== 'string') return false;
  
  const urlLower = url.toLowerCase();
  
  // 分离URL的主体部分和查询字符串部分
  const urlParts = urlLower.split('?');
  const mainUrl = urlParts[0]; // 主体部分（不包含查询参数）
  const queryString = urlParts[1] || ''; // 查询字符串部分
  
  // 1. 直接匹配.m3u8文件扩展名（最可靠，只检查主体URL）
  if (mainUrl.endsWith('.m3u8')) return true;
  
  // 2. 严格匹配：主体URL包含m3u8且有明确的视频流指标
  if (mainUrl.includes('m3u8')) {
    const strongIndicators = [
      'playlist',
      'master',
      'index.m3u8',
      'live.m3u8', 
      'manifest.m3u8',
      '/hls/'
    ];
    
    const hasStrongIndicator = strongIndicators.some(indicator => mainUrl.includes(indicator));
    if (hasStrongIndicator) return true;
  }
  
  // 3. 查询参数中的格式指定（但需要主体URL也有相关特征）
  if (queryString && 
      (queryString.includes('format=m3u8') || queryString.includes('type=m3u8')) &&
      (mainUrl.includes('video') || mainUrl.includes('live') || mainUrl.includes('stream'))) {
    return true;
  }
  
  return false;
}

// 向后台脚本报告发现的M3U8链接
function reportM3U8(url, source) {
  chrome.runtime.sendMessage({
    type: 'M3U8_FOUND_BY_CONTENT',
    url: url,
    source: source
  }).catch(() => {}); // 忽略错误
}

// 监控fetch请求
if (window.fetch) {
  const originalFetch = window.fetch;
  window.fetch = function(input, options) {
    const url = typeof input === 'string' ? input : (input && input.url ? input.url : '');
    
    if (isM3U8Url(url)) {
      reportM3U8(url, 'Fetch Request');
    }
    
    // 调用原始fetch并监控响应
    return originalFetch.apply(this, arguments).then(response => {
      if (response && response.url && isM3U8Url(response.url)) {
        reportM3U8(response.url, 'Fetch Response');
      }
      
      // 检查Content-Type
      const contentType = response.headers.get('content-type') || '';
      if (contentType.includes('mpegurl') || contentType.includes('m3u8')) {
        reportM3U8(response.url, 'Fetch Content-Type');
      }
      
      return response;
    });
  };
}

// 监控XMLHttpRequest
if (window.XMLHttpRequest) {
  const originalXHROpen = XMLHttpRequest.prototype.open;
  const originalXHRSend = XMLHttpRequest.prototype.send;
  
  XMLHttpRequest.prototype.open = function(method, url) {
    this._m3u8_url = url;
    
    if (isM3U8Url(url)) {
      reportM3U8(url, 'XHR Request');
    }
    
    return originalXHROpen.apply(this, arguments);
  };
  
  XMLHttpRequest.prototype.send = function(data) {
    const xhr = this;
    
    // 监听响应
    xhr.addEventListener('readystatechange', function() {
      if (xhr.readyState === 4) {
        const url = xhr.responseURL || xhr._m3u8_url;
        
        if (url && isM3U8Url(url)) {
          reportM3U8(url, 'XHR Response');
        }
        
        // 检查响应头
        try {
          const contentType = xhr.getResponseHeader('content-type') || '';
          if (contentType.includes('mpegurl') || contentType.includes('m3u8')) {
            reportM3U8(url, 'XHR Content-Type');
          }
        } catch (e) {}
        
        // 检查响应内容（更精确的验证）
        try {
          const responseText = xhr.responseText || '';
          if (responseText && isValidM3U8Content(responseText)) {
            reportM3U8(url, 'XHR Verified Content');
          }
        } catch (e) {}
      }
    });
    
    return originalXHRSend.apply(this, arguments);
  };
}

// 扫描页面中的媒体元素
function scanMediaElements() {
  const selectors = [
    'video[src]',
    'audio[src]', 
    'source[src]',
    '[src*="m3u8"]',
    '[data-src*="m3u8"]',
    '[href*="m3u8"]',
    'video[data-src]',
    'audio[data-src]'
  ];
  
  selectors.forEach(selector => {
    try {
      const elements = document.querySelectorAll(selector);
      elements.forEach(elem => {
        const src = elem.src || elem.getAttribute('data-src') || elem.href;
        if (src && isM3U8Url(src)) {
          reportM3U8(src, 'DOM Element');
        }
      });
    } catch (e) {}
  });
}

// 监控DOM变化
const observer = new MutationObserver(function(mutations) {
  mutations.forEach(function(mutation) {
    mutation.addedNodes.forEach(function(node) {
      if (node.nodeType === 1) { // Element node
        // 检查新添加的媒体元素
        if (node.tagName === 'VIDEO' || node.tagName === 'AUDIO' || node.tagName === 'SOURCE') {
          const src = node.src || node.getAttribute('data-src');
          if (src && isM3U8Url(src)) {
            reportM3U8(src, 'DOM Mutation');
          }
        }
        
        // 检查子元素
        try {
          const mediaElements = node.querySelectorAll && node.querySelectorAll('video, audio, source');
          if (mediaElements) {
            mediaElements.forEach(elem => {
              const src = elem.src || elem.getAttribute('data-src');
              if (src && isM3U8Url(src)) {
                reportM3U8(src, 'DOM Child');
              }
            });
          }
        } catch (e) {}
      }
    });
  });
});

// 开始监控DOM变化
if (document.body) {
  observer.observe(document.body, { childList: true, subtree: true });
} else {
  // 如果body还没加载，等待
  document.addEventListener('DOMContentLoaded', function() {
    observer.observe(document.body, { childList: true, subtree: true });
  });
}

// 初始扫描
scanMediaElements();

// 定期扫描
setInterval(scanMediaElements, 5000);

console.log('M3U8 Monitor: 内容脚本监控已启动');