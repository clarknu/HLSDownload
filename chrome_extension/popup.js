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
                        listElement.innerHTML = '<div class="empty-message">暂无捕获的M3U8文件<br>请访问包含视频的网页</div>';
                    } else {
                        listElement.innerHTML = '<div class="empty-message">当前过滤条件下无结果<br>请尝试其他过滤选项</div>';
                    }
                } else {
                    renderM3U8List();
                }
            }
        });
    }
    
    // 渲染M3U8列表
    function renderM3U8List() {
        const html = filteredM3U8s.map((item, index) => {
            const time = new Date(item.timestamp).toLocaleString();
            const isVerified = item.source.includes('Verified') || item.url.toLowerCase().includes('.m3u8');
            const statusIcon = isVerified ? '✅' : '⚠️';
            
            return `
                <div class="m3u8-item">
                    <div class="m3u8-url">${statusIcon} ${item.url}</div>
                    <div class="m3u8-info">
                        <span>🌐 ${item.domain}</span>
                        <span>⏰ ${time}</span>
                        <span>📍 ${item.source}</span>
                    </div>
                    <button class="copy-btn" data-url="${item.url}">复制链接</button>
                </div>
            `;
        }).join('');
        
        listElement.innerHTML = html;
        
        // 添加复制按钮事件
        document.querySelectorAll('.copy-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const url = this.getAttribute('data-url');
                copyToClipboard(url);
                this.textContent = '已复制!';
                setTimeout(() => {
                    this.textContent = '复制链接';
                }, 1000);
            });
        });
    }
    
    // 复制到剪贴板
    function copyToClipboard(text) {
        navigator.clipboard.writeText(text).then(function() {
            console.log('已复制到剪贴板:', text);
        }).catch(function(err) {
            console.error('复制失败:', err);
        });
    }
    
    // 刷新按钮
    refreshBtn.addEventListener('click', function() {
        updateDisplay();
    });
    
    // 清空按钮
    clearBtn.addEventListener('click', function() {
        if (confirm('确定要清空所有捕获的M3U8链接吗？')) {
            chrome.runtime.sendMessage({ type: 'CLEAR_CAPTURED_M3U8S' }, function(response) {
                if (response && response.success) {
                    updateDisplay();
                }
            });
        }
    });
    
    // 导出按钮
    exportBtn.addEventListener('click', function() {
        if (capturedM3U8s.length === 0) {
            alert('没有可导出的M3U8链接');
            return;
        }
        
        const exportData = {
            exportTime: new Date().toISOString(),
            count: capturedM3U8s.length,
            m3u8s: capturedM3U8s
        };
        
        const dataStr = JSON.stringify(exportData, null, 2);
        const blob = new Blob([dataStr], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = `m3u8_export_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });
    
    // 复制所有链接按钮
    copyAllBtn.addEventListener('click', function() {
        if (capturedM3U8s.length === 0) {
            alert('没有可复制的M3U8链接');
            return;
        }
        
        const allUrls = capturedM3U8s.map(item => item.url).join('\n');
        copyToClipboard(allUrls);
        
        copyAllBtn.textContent = '已复制!';
        setTimeout(() => {
            copyAllBtn.textContent = '复制所有链接';
        }, 1000);
    });
    
    // 保存为TXT按钮
    saveTxtBtn.addEventListener('click', function() {
        if (capturedM3U8s.length === 0) {
            alert('没有可保存的M3U8链接');
            return;
        }
        
        const content = capturedM3U8s.map((item, index) => {
            const time = new Date(item.timestamp).toLocaleString();
            return `${index + 1}. ${item.url}\n   域名: ${item.domain}\n   时间: ${time}\n   来源: ${item.source}\n`;
        }).join('\n');
        
        const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = `m3u8_links_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });
    
    // 过滤选择器事件
    filterSelect.addEventListener('change', function() {
        updateDisplay();
    });
    
    // 监听来自background的消息
    chrome.runtime.onMessage.addListener(function(message, sender, sendResponse) {
        if (message.type === 'M3U8_FOUND') {
            updateDisplay();
        }
    });
    
    // 初始加载
    updateDisplay();
});