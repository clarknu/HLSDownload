// Popup页面的JavaScript
document.addEventListener('DOMContentLoaded', function() {
    console.log('M3U8 Monitor Popup: 已加载');
    
    const countElement = document.getElementById('count');
    const listElement = document.getElementById('m3u8-list');
    const refreshBtn = document.getElementById('refresh');
    const clearBtn = document.getElementById('clear');
    const exportBtn = document.getElementById('export');
    const copyAllBtn = document.getElementById('copy-all');
    const saveTxtBtn = document.getElementById('save-txt');
    const filterSelect = document.getElementById('filter-select');
    
    let capturedM3U8s = [];
    let filteredM3U8s = [];
    
    // 过滤M3U8链接
    function filterM3U8s() {
        const filterType = filterSelect.value;
        
        switch (filterType) {
            case 'verified':
                filteredM3U8s = capturedM3U8s.filter(item => 
                    item.source.includes('Verified') || 
                    item.url.toLowerCase().includes('.m3u8')
                );
                break;
            case 'direct':
                filteredM3U8s = capturedM3U8s.filter(item => 
                    item.url.toLowerCase().includes('.m3u8')
                );
                break;
            case 'unverified':
                filteredM3U8s = capturedM3U8s.filter(item => 
                    item.source.includes('Unverified')
                );
                break;
            default:
                filteredM3U8s = [...capturedM3U8s];
        }
    }
    
    // 更新显示
    function updateDisplay() {
        chrome.runtime.sendMessage({ type: 'GET_CAPTURED_M3U8S' }, function(response) {
            if (response && response.capturedM3U8s) {
                capturedM3U8s = response.capturedM3U8s;
                filterM3U8s();
                countElement.textContent = `${filteredM3U8s.length}/${capturedM3U8s.length}`;
                
                if (filteredM3U8s.length === 0) {
                    if (capturedM3U8s.length === 0) {
                        listElement.innerHTML = '<div class="empty-message">暂无M3U8历史记录<br>请访问包含视频的网页</div>';
                    } else {
                        listElement.innerHTML = '<div class="empty-message">当前过滤条件下无结果<br>请尝试其他过滤选项</div>';
                    }
                } else {
                    renderM3U8List();
                }
            }
        });
    }
    
    // 处理URL显示：缩短并提供展开功能
    function formatUrlForDisplay(url, index) {
        try {
            // 先检查是否包含查询参数
            if (!url.includes('?')) {
                return {
                    displayUrl: url,
                    needsToggle: false
                };
            }
            
            const urlObj = new URL(url);
            const baseUrl = urlObj.origin + urlObj.pathname;
            const hasQuery = urlObj.search.length > 0;
            
            if (!hasQuery) {
                // 没有查询参数，直接显示
                return {
                    displayUrl: url,
                    needsToggle: false
                };
            }
            
            // 有查询参数，默认显示基础URL
            return {
                displayUrl: baseUrl,
                fullUrl: url,
                needsToggle: true,
                isCollapsed: true
            };
        } catch (e) {
            console.warn('URL解析失败:', url, e);
            // URL解析失败，直接显示
            return {
                displayUrl: url,
                needsToggle: false
            };
        }
    }
    
    // 切换URL显示状态
    function toggleUrlDisplay(index) {
        console.log('切换URL显示，索引:', index);
        
        const itemElement = document.querySelector(`[data-url-index="${index}"]`);
        if (!itemElement || !filteredM3U8s[index]) {
            console.error('找不到元素或数据，索引:', index);
            return;
        }
        
        const urlElement = itemElement.querySelector('.m3u8-url');
        const toggleElement = itemElement.querySelector('.url-toggle');
        
        if (!urlElement || !toggleElement) {
            console.error('找不到URL元素或切换按钮');
            return;
        }
        
        const item = filteredM3U8s[index];
        const urlData = formatUrlForDisplay(item.url, index);
        
        if (!urlData.needsToggle) {
            console.log('该URL不需要切换');
            return;
        }
        
        const isCollapsed = urlElement.classList.contains('collapsed');
        const statusIcon = getStatusIcon(item);
        
        if (isCollapsed) {
            // 展开显示完整URL
            urlElement.innerHTML = `${statusIcon} ${urlData.fullUrl} <span class="url-toggle" data-index="${index}">折叠</span>`;
            urlElement.classList.remove('collapsed');
            urlElement.classList.add('expanded');
            console.log('已展开URL');
        } else {
            // 折叠显示简化URL
            urlElement.innerHTML = `${statusIcon} ${urlData.displayUrl} <span class="url-toggle" data-index="${index}">展开</span>`;
            urlElement.classList.remove('expanded');
            urlElement.classList.add('collapsed');
            console.log('已折叠URL');
        }
        
        // 重新绑定新的切换按钮事件
        const newToggleElement = urlElement.querySelector('.url-toggle');
        if (newToggleElement) {
            newToggleElement.addEventListener('click', function(e) {
                e.stopPropagation();
                const newIndex = parseInt(this.getAttribute('data-index'));
                toggleUrlDisplay(newIndex);
            });
        }
    }
    
    // 获取状态图标
    function getStatusIcon(item) {
        const isVerified = item.source.includes('Verified') || item.url.toLowerCase().includes('.m3u8');
        return isVerified ? '✅' : '⚠️';
    }
    function renderM3U8List() {
        const html = filteredM3U8s.map((item, index) => {
            const time = new Date(item.timestamp).toLocaleString();
            const statusIcon = getStatusIcon(item);
            const urlData = formatUrlForDisplay(item.url, index);
            
            // 默认显示的URL（缩短版本）
            const displayUrl = urlData.needsToggle ? urlData.displayUrl : item.url;
            
            // 切换按钮（只在需要时显示）
            const toggleButton = urlData.needsToggle ? 
                ` <span class="url-toggle" data-index="${index}">展开</span>` : '';
            
            // URL元素的样式类（只有需要切换的才添加collapsed类）
            const urlClass = urlData.needsToggle ? 'm3u8-url collapsed clickable' : 'm3u8-url';
            
            return `
                <div class="m3u8-item" data-url="${item.url}" data-url-index="${index}">
                    <div class="${urlClass}">
                        ${statusIcon} ${displayUrl}${toggleButton}
                    </div>
                    <div class="m3u8-info">
                        <span>🌐 ${item.domain}</span>
                        <span>⏰ ${time}</span>
                        <span>📍 ${item.source}</span>
                    </div>
                    <div class="button-group">
                        <button class="copy-btn" data-url="${item.url}">复制链接</button>
                        <button class="delete-btn" data-url="${item.url}">删除</button>
                    </div>
                </div>
            `;
        }).join('');
        
        listElement.innerHTML = html;
        
        // 添加URL切换按钮事件监听
        document.querySelectorAll('.url-toggle').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                const index = parseInt(this.getAttribute('data-index'));
                toggleUrlDisplay(index);
            });
        });
        
        // 添加复制按钮事件监听
        document.querySelectorAll('.copy-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const url = this.getAttribute('data-url');
                copyToClipboard(url);
            });
        });
        
        // 添加删除按钮事件监听
        document.querySelectorAll('.delete-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const url = this.getAttribute('data-url');
                deleteM3U8Item(url);
            });
        });
    }
    
    // 复制到剪贴板
    function copyToClipboard(text) {
        navigator.clipboard.writeText(text).then(function() {
            console.log('链接已复制到剪贴板:', text);
            // 显示复制成功的提示
            showToast('链接已复制到剪贴板');
        }).catch(function(err) {
            console.error('复制失败:', err);
            // 显示复制失败的提示
            showToast('复制失败，请手动复制', 'error');
        });
    }
    
    // 显示提示信息
    function showToast(message, type = 'success') {
        const toast = document.createElement('div');
        toast.textContent = message;
        toast.style.cssText = `
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: ${type === 'error' ? '#f44336' : '#4caf50'};
            color: white;
            padding: 8px 16px;
            border-radius: 4px;
            z-index: 10000;
            font-size: 12px;
        `;
        document.body.appendChild(toast);
        
        setTimeout(() => {
            document.body.removeChild(toast);
        }, 2000);
    }
    
    // 导出为JSON
    function exportJSON() {
        const data = {
            timestamp: new Date().toISOString(),
            count: filteredM3U8s.length,
            links: filteredM3U8s.map(item => {
                return {
                    // 基本信息
                    url: item.url,
                    domain: item.domain,
                    timestamp: item.timestamp,
                    source: item.source,
                    method: item.method || 'GET',
                    
                    // 页面上下文（用于设置正确的Referer）
                    pageUrl: item.pageUrl || '',
                    pageTitle: item.pageTitle || '',
                    
                    // 模拟浏览器请求的关键请求头
                    headers: {
                        userAgent: item.headers?.userAgent || navigator.userAgent,
                        referer: item.headers?.referer || item.pageUrl || '',
                        origin: item.headers?.origin || '',
                        cookie: item.headers?.cookie || ''
                    },
                    
                    // 现代浏览器安全策略头
                    securityHeaders: {
                        secFetchSite: item.securityHeaders?.secFetchSite || 'same-origin',
                        secFetchMode: item.securityHeaders?.secFetchMode || 'cors',
                        secFetchDest: item.securityHeaders?.secFetchDest || 'empty'
                    }
                };
            })
        };
        
        const timestamp = new Date().toISOString().replace(/:/g, '-').replace(/\./g, '-').slice(0, 19);
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `m3u8_links_${timestamp}.json`;
        a.click();
        URL.revokeObjectURL(url);
    }
    
    // 复制所有链接
    function copyAllLinks() {
        const urls = filteredM3U8s.map(item => item.url).join('\n');
        copyToClipboard(urls);
    }
    
    // 保存为TXT
    function saveTxt() {
        const content = filteredM3U8s.map(item => {
            const lines = [
                `URL: ${item.url}`,
                `域名: ${item.domain}`,
                `时间: ${new Date(item.timestamp).toLocaleString()}`,
                `来源: ${item.source}`,
                `请求方法: ${item.method || 'GET'}`,
                `页面URL: ${item.pageUrl || '未知'}`,
                `页面标题: ${item.pageTitle || '未知'}`,
                `User-Agent: ${item.headers?.userAgent || navigator.userAgent}`,
                `Referer: ${item.headers?.referer || item.pageUrl || '无'}`,
                `Origin: ${item.headers?.origin || '无'}`,
                `Cookie: ${item.headers?.cookie || '无'}`,
                `Sec-Fetch-Site: ${item.securityHeaders?.secFetchSite || 'same-origin'}`,
                `Sec-Fetch-Mode: ${item.securityHeaders?.secFetchMode || 'cors'}`,
                `Sec-Fetch-Dest: ${item.securityHeaders?.secFetchDest || 'empty'}`
            ];
            
            return lines.join('\n') + '\n' + '='.repeat(80);
        }).join('\n\n');
        
        const header = [
            'M3U8 链接导出文件 - 模拟浏览器请求信息',
            `导出时间: ${new Date().toLocaleString()}`,
            `总数: ${filteredM3U8s.length} 个链接`,
            '='.repeat(80),
            ''
        ].join('\n');
        
        const fullContent = header + content;
        
        const timestamp = new Date().toISOString().replace(/:/g, '-').replace(/\./g, '-').slice(0, 19);
        const blob = new Blob([fullContent], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `m3u8_links_${timestamp}.txt`;
        a.click();
        URL.revokeObjectURL(url);
    }
    
    // 删除单个M3U8项目
    function deleteM3U8Item(url) {
        if (confirm('确定要删除这个链接吗？\n\n' + url)) {
            chrome.runtime.sendMessage({ 
                type: 'DELETE_M3U8_ITEM', 
                url: url 
            }, function(response) {
                if (response && response.success) {
                    updateDisplay();
                    showToast('已删除链接');
                    console.log('已删除链接，剩余', response.count, '个');
                } else {
                    showToast('删除失败', 'error');
                }
            });
        }
    }
    
    // 清空所有已捕获的链接
    function clearCaptured() {
        if (confirm('确定要清空所有已捕获的M3U8链接吗？\n\n此操作不可撤销！')) {
            chrome.runtime.sendMessage({ type: 'CLEAR_CAPTURED_M3U8S' }, function(response) {
                if (response && response.success) {
                    updateDisplay();
                    showToast('已清空所有链接');
                    console.log('已清空所有历史链接');
                } else {
                    showToast('清空失败', 'error');
                }
            });
        }
    }
    
    // 事件监听
    refreshBtn.addEventListener('click', updateDisplay);
    clearBtn.addEventListener('click', clearCaptured);
    exportBtn.addEventListener('click', exportJSON);
    copyAllBtn.addEventListener('click', copyAllLinks);
    saveTxtBtn.addEventListener('click', saveTxt);
    filterSelect.addEventListener('change', updateDisplay);
    
    // 监听来自background script的消息
    chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
        if (message.type === 'M3U8_FOUND') {
            // 实时更新显示
            updateDisplay();
        }
    });
    
    // 初始化
    updateDisplay();
    
    // 添加调试信息
    console.log('M3U8 Monitor Popup: 初始化完成，使用addEventListener绑定事件');
});