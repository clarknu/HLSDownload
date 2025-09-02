// 后台脚本 - 监控网络请求
console.log('M3U8 Monitor: 后台脚本已启动');

// 存储捕获的M3U8链接
let capturedM3U8s = [];

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
  
  // 2. 严格匹配：主体URL包含m3u8且有强指标
  if (mainUrl.includes('m3u8')) {
    // 检查是否有视频流的强指标（只在主体URL中检查）
    const strongIndicators = [
      'playlist',
      'master', 
      'index.m3u8',
      'live.m3u8',
      'manifest.m3u8',
      'hls',
      'stream'
    ];
    
    const hasStrongIndicator = strongIndicators.some(indicator => 
      mainUrl.includes(indicator)
    );
    
    if (hasStrongIndicator) return true;
  }
  
  // 3. 非常严格的路径检查：避免误判普通网页（只检查主体URL）
  if (mainUrl.includes('m3u8') && 
      (mainUrl.includes('/video/') || 
       mainUrl.includes('/live/') || 
       mainUrl.includes('/stream/') ||
       mainUrl.includes('/hls/'))) {
    return true;
  }
  
  // 4. 查询参数中的格式指定（但需要主体URL也有相关特征）
  if (queryString && 
      (queryString.includes('format=m3u8') || queryString.includes('type=m3u8')) &&
      (mainUrl.includes('video') || mainUrl.includes('live') || mainUrl.includes('stream'))) {
    return true;
  }
  
  return false;
}

// 检查响应头是否为M3U8相关
function isM3U8ContentType(headers) {
  const contentType = headers['content-type'] || '';
  const contentTypeLower = contentType.toLowerCase();
  
  // 只检查标准的M3U8 MIME类型
  return contentTypeLower.includes('application/vnd.apple.mpegurl') ||
         contentTypeLower.includes('application/x-mpegurl') ||
         contentTypeLower.includes('audio/mpegurl') ||
         contentTypeLower.includes('video/mp2t'); // TS段的MIME类型
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

// 处理发现的M3U8链接
function handleM3U8Found(url, details, source, extraInfo = {}) {
  const domain = new URL(url).hostname;
  const timestamp = new Date().toISOString();
  
  // 检查是否已经存在
  const exists = capturedM3U8s.some(item => item.url === url);
  if (exists) return;
  
  // 对于非直接.m3u8扩展名的URL，进行额外验证
  const urlLower = url.toLowerCase();
  const needsVerification = !urlLower.includes('.m3u8') && urlLower.includes('m3u8');
  
  if (needsVerification && source !== 'XHR Verified Content' && source !== 'Verified by Content') {
    // 尝试获取内容进行验证
    verifyM3U8Content(url, details, source, extraInfo);
    return;
  }
  
  // 只收集下载时需要的关键信息
  const m3u8Info = {
    url: url,
    domain: domain,
    timestamp: timestamp,
    source: source,
    method: details.method || 'GET',
    
    // 页面上下文（用于设置正确的Referer）
    pageUrl: extraInfo.pageUrl || '',
    pageTitle: extraInfo.pageTitle || '',
    
    // 关键请求头（用于模拟浏览器请求）
    headers: {
      userAgent: extraInfo.userAgent || navigator.userAgent,
      referer: extraInfo.referer || extraInfo.pageUrl || '',
      origin: extraInfo.origin || '',
      cookie: extraInfo.cookies || ''
    },
    
    // 安全策略头（现代浏览器必需）
    securityHeaders: {
      secFetchSite: extraInfo.secFetchSite || 'same-origin',
      secFetchMode: extraInfo.secFetchMode || 'cors',
      secFetchDest: extraInfo.secFetchDest || 'empty'
    }
  };
  
  capturedM3U8s.push(m3u8Info);
  console.log('M3U8 Monitor: 发现M3U8链接', url, source);
  
  // 发送通知到popup
  chrome.runtime.sendMessage({
    type: 'M3U8_FOUND',
    data: m3u8Info
  }).catch(() => {}); // 忽略没有接收者的错误
  
  // 保存到storage
  chrome.storage.local.set({
    capturedM3U8s: capturedM3U8s
  });
}

// 验证M3U8内容
function verifyM3U8Content(url, details, originalSource, extraInfo = {}) {
  fetch(url, {
    method: 'GET',
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
  })
  .then(response => {
    if (!response.ok) throw new Error('Network response was not ok');
    return response.text();
  })
  .then(content => {
    if (isValidM3U8Content(content)) {
      // 内容验证通过，记录为正式的M3U8文件
      handleM3U8Found(url, details, 'Verified by Content', extraInfo);
    } else {
      console.log('M3U8 Monitor: 内容验证失败，不是真正的M3U8文件:', url);
    }
  })
  .catch(error => {
    console.log('M3U8 Monitor: 无法验证内容:', url, error.message);
    // 验证失败，但如果URL看起来非常可靠，仍然记录
    if (url.toLowerCase().includes('.m3u8') || 
        (url.toLowerCase().includes('playlist') && url.toLowerCase().includes('m3u8'))) {
      handleM3U8Found(url, details, originalSource + ' (Unverified)', extraInfo);
    }
  });
}

// 存储请求头信息的临时存储
const requestHeadersCache = new Map();
const pageInfoCache = new Map();

// 监听请求头（发送时）
chrome.webRequest.onBeforeSendHeaders.addListener(
  function(details) {
    if (isM3U8Url(details.url)) {
      // 只收集关键的模拟请求头
      const headers = {};
      if (details.requestHeaders) {
        details.requestHeaders.forEach(header => {
          const name = header.name.toLowerCase();
          // 只保留模拟浏览器请求所需的关键头
          if (['referer', 'origin', 'user-agent', 'cookie', 
               'sec-fetch-site', 'sec-fetch-mode', 'sec-fetch-dest'].includes(name)) {
            headers[name] = header.value;
          }
        });
      }
      
      // 缓存关键信息
      requestHeadersCache.set(details.requestId, {
        userAgent: headers['user-agent'] || navigator.userAgent,
        referer: headers['referer'] || '',
        origin: headers['origin'] || '',
        cookies: headers['cookie'] || '',
        secFetchSite: headers['sec-fetch-site'] || '',
        secFetchMode: headers['sec-fetch-mode'] || '',
        secFetchDest: headers['sec-fetch-dest'] || ''
      });
    }
  },
  {
    urls: ["<all_urls>"],
    types: ["main_frame", "sub_frame", "xmlhttprequest", "other", "media"]
  },
  ["requestHeaders"]
);

// 监听网络请求开始
chrome.webRequest.onBeforeRequest.addListener(
  function(details) {
    if (isM3U8Url(details.url)) {
      // 获取缓存的请求头信息
      const cachedInfo = requestHeadersCache.get(details.requestId) || {};
      const pageInfo = pageInfoCache.get(details.tabId) || {};
      
      const extraInfo = {
        ...cachedInfo,
        pageUrl: pageInfo.url || '',
        pageTitle: pageInfo.title || ''
      };
      
      handleM3U8Found(details.url, details, 'Request', extraInfo);
    }
  },
  {
    urls: ["<all_urls>"],
    types: ["main_frame", "sub_frame", "xmlhttprequest", "other", "media"]
  }
);

// 监听网络响应头
chrome.webRequest.onResponseStarted.addListener(
  function(details) {
    if (details.responseHeaders) {
      const headers = {};
      details.responseHeaders.forEach(header => {
        headers[header.name.toLowerCase()] = header.value;
      });
      
      if (isM3U8Url(details.url) || isM3U8ContentType(headers)) {
        // 获取缓存的请求信息
        const cachedInfo = requestHeadersCache.get(details.requestId) || {};
        const pageInfo = pageInfoCache.get(details.tabId) || {};
        
        const extraInfo = {
          ...cachedInfo,
          pageUrl: pageInfo.url || '',
          pageTitle: pageInfo.title || ''
        };
        
        handleM3U8Found(details.url, details, 'Response', extraInfo);
        
        // 清理缓存（防止内存泄漏）
        requestHeadersCache.delete(details.requestId);
      }
    }
  },
  {
    urls: ["<all_urls>"],
    types: ["main_frame", "sub_frame", "xmlhttprequest", "other", "media"]
  },
  ["responseHeaders"]
);

// 监听来自content script的消息
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'M3U8_FOUND_BY_CONTENT') {
    const pageInfo = pageInfoCache.get(sender.tab.id) || {};
    const extraInfo = {
      pageUrl: pageInfo.url || sender.tab.url || '',
      pageTitle: pageInfo.title || sender.tab.title || ''
    };
    handleM3U8Found(message.url, { tabId: sender.tab.id }, 'Content Script', extraInfo);
  } else if (message.type === 'PAGE_INFO') {
    // 收集页面信息
    pageInfoCache.set(sender.tab.id, {
      url: message.url,
      title: message.title,
      timestamp: Date.now()
    });
  } else if (message.type === 'GET_CAPTURED_M3U8S') {
    sendResponse({ capturedM3U8s: capturedM3U8s });
  } else if (message.type === 'CLEAR_CAPTURED_M3U8S') {
    capturedM3U8s = [];
    chrome.storage.local.set({ capturedM3U8s: [] });
    sendResponse({ success: true });
  } else if (message.type === 'DELETE_M3U8_ITEM') {
    // 删除单个M3U8链接项目
    const urlToDelete = message.url;
    capturedM3U8s = capturedM3U8s.filter(item => item.url !== urlToDelete);
    chrome.storage.local.set({ capturedM3U8s: capturedM3U8s });
    console.log('M3U8 Monitor: 已删除链接', urlToDelete);
    sendResponse({ success: true, count: capturedM3U8s.length });
  }
});

// 监听标签页更新事件
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'complete' && tab.url && tab.title) {
    pageInfoCache.set(tabId, {
      url: tab.url,
      title: tab.title,
      timestamp: Date.now()
    });
  }
});

// 清理关闭的标签页缓存
chrome.tabs.onRemoved.addListener((tabId) => {
  pageInfoCache.delete(tabId);
});

// 从storage中恢复数据
chrome.storage.local.get(['capturedM3U8s'], function(result) {
  if (result.capturedM3U8s) {
    capturedM3U8s = result.capturedM3U8s;
    console.log('M3U8 Monitor: 恢复了', capturedM3U8s.length, '个已捕获的M3U8链接');
  }
});

console.log('M3U8 Monitor: 网络监控已启动');