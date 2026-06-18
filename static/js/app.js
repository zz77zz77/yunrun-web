// ---- 全局状态 ----
let userInfo = null;
let allRuns = [];
let currentTableName = '';
let selectedTaskFile = null;

// ---- 初始化 ----
async function init() {
  const res = await api('/api/user/info');
  if (res.code === 401) { location.href = '/login'; return; }
  userInfo = res.data;
  renderUserInfo();
  switchPage('home');
  loadTaskFiles();
  loadCronTaskFiles();
  loadHomeStats();
  startRunningPoller();
  // 检查学校是否有内置任务文件，决定是否显示随机文件开关
  api('/api/school/has_tasks').then(r => {
    const show = r.has_tasks ? '' : 'none';
    const cronEl = document.getElementById('cron-school-file-toggle');
    const onceEl = document.getElementById('once-school-file-toggle');
    if (cronEl) cronEl.style.display = show;
    if (onceEl) onceEl.style.display = show;
  });
}

function renderUserInfo() {
  const u = userInfo;
  document.getElementById('sidebar-user').textContent = u.real_name || u.username;
  document.getElementById('home-name').textContent = u.real_name || '-';
  document.getElementById('home-school').textContent = u.school_name || '-';
  document.getElementById('home-device').textContent = u.device_name || '-';
  const expEl = document.getElementById('home-expire');
  if (u.user_time) {
    expEl.textContent = u.user_time;
    const expired = u.now_time && u.now_time >= u.user_time;
    expEl.style.color = expired ? '#ef4444' : '#10b981';
  } else {
    expEl.textContent = '未获取';
  }
  // 只有安徽邮电学院用户才显示口袋报名入口
  const isAhptc = (u.school_name || '').includes('安徽邮电');
  document.querySelectorAll('[data-page="signup"], a[href="/signup"]').forEach(el => {
    el.style.display = isAhptc ? '' : 'none';
  });
  // 个人中心
  const memberEl = document.getElementById('member-info');
  memberEl.innerHTML = infoItem('用户名', u.username) + infoItem('会员有效期', u.user_time || '未获取') +
    infoItem('当前时间', u.now_time || '-') + infoItem('状态', !u.user_time ? '⚠️ 未获取' : (u.now_time && u.now_time < u.user_time ? '✅ 有效' : '❌ 已过期'));
  const s = u.student_info || {};
  document.getElementById('student-info').innerHTML =
    infoItem('姓名', s.realName) + infoItem('学号', s.userName) +
    infoItem('性别', s.sex === 1 ? '男' : '女') + infoItem('学院', s.facName) +
    infoItem('专业', s.pfsName) + infoItem('班级', s.className) +
    infoItem('校区', s.campusName) + infoItem('年级', s.grade);
}

function infoItem(label, val) {
  return `<div class="info-item"><label>${label}</label><span>${val || '-'}</span></div>`;
}

async function loadHomeStats() {
  const res = await api('/api/home/stats');
  const loading = document.getElementById('home-stats-loading');
  const content = document.getElementById('home-stats-content');
  const errEl = document.getElementById('home-stats-error');
  if (res.code !== 200 || !res.data) {
    loading.style.display = 'none';
    errEl.style.display = 'block';
    errEl.textContent = res.code !== 200 ? ('获取失败: ' + res.msg) : '暂无跑步记录';
    return;
  }
  const d = res.data;
  loading.style.display = 'none';
  content.style.display = 'block';
  document.getElementById('home-term-name').textContent = d.term;
  document.getElementById('home-progress-text').textContent = `${d.qualified} / ${d.target}`;
  document.getElementById('home-progress-bar').style.width = d.percent + '%';
  const pctEl = document.getElementById('home-progress-pct');
  pctEl.textContent = d.percent + '%';
  pctEl.style.color = d.percent >= 100 ? '#10b981' : d.percent >= 50 ? '#f59e0b' : '#ef4444';
  document.getElementById('home-qualified').textContent = d.qualified;
  document.getElementById('home-unqualified').textContent = d.unqualified;
  document.getElementById('home-total-runs').textContent = d.total;
  document.getElementById('home-distance').textContent = d.distance + ' km';
}

// ---- 页面切换 ----
function switchPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item, .bottom-nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + name)?.classList.add('active');
  document.querySelectorAll(`[data-page="${name}"]`).forEach(el => el.classList.add('active'));
  if (name === 'history' && !currentTableName) loadTerms();
  if (name === 'cron') { loadCronJobs(); loadCronTaskFiles(); loadEmailConfig(); }
  if (name === 'logs') loadLogs();
}

document.querySelectorAll('.nav-item, .bottom-nav-item').forEach(el => {
  el.addEventListener('click', e => {
    if (el.dataset.external) return; // 外部链接直接跳转
    e.preventDefault();
    switchPage(el.dataset.page);
  });
});

// ---- API 工具 ----
async function api(url, opts = {}) {
  try {
    const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, credentials: 'include', ...opts });
    return res.json();
  } catch (e) { return { code: 500, msg: e.message }; }
}

function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `msg ${type}`;
  el.textContent = msg;
  el.style.cssText = 'position:fixed;top:20px;right:20px;z-index:9999;min-width:200px;';
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3000);
}

async function logout() {
  await api('/api/logout', { method: 'POST' });
  location.href = '/login';
}

// ---- 跑步功能 ----
async function loadTaskFiles() {
  const res = await api('/api/run/task_files');
  const el = document.getElementById('task-files-list');
  if (!res.data || res.data.length === 0) {
    el.innerHTML = '<div class="text-muted">暂无任务文件，请上传</div>';
    return;
  }
  el.innerHTML = res.data.map((f, i) => `
    <div class="cron-job-item" style="margin-bottom:8px">
      <div class="flex-between">
        <div>
          <span style="font-weight:600">${f.name}</span>
          <span class="text-muted" style="margin-left:10px">${f.mileage || '?'} km · ${Math.round((f.duration||0)/60)} 分钟 · ${f.points||0} 点</span>
        </div>
        <div class="btn-row">
          <button class="btn btn-sm btn-primary" data-idx="${i}" onclick="selectTaskFileByIdx(this)">选择</button>
          <a class="btn btn-sm btn-outline" href="/api/run/download_task?filename=${encodeURIComponent(f.name)}" download="${f.name}">⬇️ 下载</a>
          <button class="btn btn-sm btn-danger" data-idx="${i}" onclick="deleteTaskFileByIdx(this)">删除</button>
        </div>
      </div>
    </div>`).join('');
  // 把文件列表缓存到全局，供按钮回调使用
  window._taskFiles = res.data;
}

function selectTaskFileByIdx(btn) {
  const f = window._taskFiles[btn.dataset.idx];
  if (f) selectTaskFile(f.name, f.name, f.mileage, f.duration);
}

async function deleteTaskFileByIdx(btn) {
  const f = window._taskFiles[btn.dataset.idx];
  if (f) await deleteTaskFile(f.name);
}

function selectTaskFile(filename, name, mileage, duration) {
  selectedTaskFile = filename;
  document.getElementById('run-panel').style.display = 'block';
  document.getElementById('selected-task-info').innerHTML =
    `<b>已选择：</b>${name}<br>距离：${mileage} km，时长：${Math.round(duration/60)} 分钟`;
}

async function uploadTaskFile(input) {
  const file = input.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch('/api/run/upload_task', { method: 'POST', body: fd, credentials: 'include' }).then(r => r.json());
  const infoEl = document.getElementById('upload-info');
  if (res.code === 200) {
    infoEl.innerHTML = `✅ 上传成功：${res.info.mileage} km · ${Math.round(res.info.duration/60)} 分钟 · ${res.info.points} 个轨迹点`;
    infoEl.className = 'info-box mt-10';
    infoEl.classList.remove('hidden');
    loadTaskFiles();
    loadCronTaskFiles();
  } else {
    infoEl.innerHTML = '❌ ' + res.msg;
    infoEl.className = 'msg error mt-10';
    infoEl.classList.remove('hidden');
  }
  input.value = '';
}

async function deleteTaskFile(filename) {
  if (!confirm('确认删除该任务文件？')) return;
  const res = await api('/api/run/delete_task', { method: 'POST', body: JSON.stringify({ filename }) });
  toast(res.msg, res.code === 200 ? 'success' : 'error');
  loadTaskFiles();
  loadCronTaskFiles();
}

let _currentRunId = null;  // 当前跑步 run_id

async function startRun() {
  if (!selectedTaskFile) { toast('请先选择任务文件', 'error'); return; }
  const btn = document.getElementById('start-run-btn');
  btn.disabled = true;
  btn.textContent = '启动中...';
  const res = await api('/api/run/start', { method: 'POST', body: JSON.stringify({ task_file: selectedTaskFile }) });
  if (res.code === 200) {
    _currentRunId = res.run_id;
    document.getElementById('run-status').classList.remove('hidden');
    document.getElementById('run-live-panel').style.display = 'block';
    document.getElementById('run-live-panel').classList.remove('hidden');
    document.getElementById('stop-run-btn').classList.remove('hidden');
    initRunMap(res.all_points || [], res.total || 0);
    subscribeRunEvents(res.run_id, res.total || 0);
    toast('跑步任务已在后台启动，可关闭页面', 'success');
  } else {
    toast(res.msg, 'error');
  }
  btn.disabled = false;
  btn.textContent = '🏃 开始跑步';
}

async function stopRun() {
  const runId = _currentRunId || (_activeRunData && _activeRunData.run_id);
  if (!runId) { toast('没有正在运行的任务', 'error'); return; }
  if (!confirm('确认停止当前跑步任务？')) return;
  const res = await api('/api/run/stop', { method: 'POST', body: JSON.stringify({ run_id: runId }) });
  toast(res.msg, res.code === 200 ? 'success' : 'error');
  if (res.code === 200) {
    document.getElementById('stop-run-btn').classList.add('hidden');
  }
}

// ---- 地图 ----
let _map = null;
let _polyline = null;
let _livePoints = [];
let _allPolyline = null;

const AMAP_KEY = window.__AMAP_KEY || '';

function parsePoint(pointStr) {
  if (!pointStr) return null;
  const parts = pointStr.split(',');
  if (parts.length < 2) return null;
  const a = parseFloat(parts[0]), b = parseFloat(parts[1]);
  if (isNaN(a) || isNaN(b)) return null;
  // 高德地图用 [lng, lat]，中国经度 73-135
  if (a > 73 && a < 135) return [a, b];
  return [b, a];
}

function initRunMap(allPoints, total) {
  _livePoints = [];
  if (_map) { _map.destroy(); _map = null; }

  window._AMapSecurityConfig = { securityJsCode: window.__AMAP_SECURITY_CODE || AMAP_KEY };
  _map = new AMap.Map('run-map', { zoom: 16, mapStyle: 'amap://styles/normal' });

  // 灰色预览全路径
  if (allPoints && allPoints.length > 0) {
    const coords = allPoints.map(parsePoint).filter(Boolean);
    if (coords.length > 0) {
      _allPolyline = new AMap.Polyline({
        path: coords, strokeColor: '#cbd5e1', strokeWeight: 4, strokeOpacity: 0.6
      });
      _map.add(_allPolyline);
      _map.setFitView([_allPolyline]);
    }
  }

  // 红色实时路径
  _polyline = new AMap.Polyline({
    path: [], strokeColor: '#ef4444', strokeWeight: 5,
    strokeOpacity: 0.9, lineJoin: 'round', lineCap: 'round'
  });
  _map.add(_polyline);
  document.getElementById('map-point-count').textContent = `0 / ${total} 点`;
}

function addMapPoint(pointStr, current, total) {
  const coord = parsePoint(pointStr);
  if (!coord || !_map) return;
  _livePoints.push(coord);
  _polyline.setPath(_livePoints);
  _map.setCenter(coord);
  document.getElementById('map-point-count').textContent = `${current} / ${total} 点`;
  if (total > 0) {
    const pct = Math.round(current / total * 100);
    document.getElementById('run-progress-text').textContent = `进度 ${pct}% (${current}/${total})`;
  }
}

function subscribeRunEvents(runId, total) {
  const logBox = document.getElementById('live-log-box');
  const es = new EventSource(`/api/run/events/${runId}`);

  es.addEventListener('log', e => {
    const d = JSON.parse(e.data);
    const div = document.createElement('div');
    div.className = 'log-entry';
    div.innerHTML = `<span class="log-time">${d.time}</span><span class="log-msg">${d.msg}</span>`;
    logBox.appendChild(div);
    logBox.scrollTop = logBox.scrollHeight;
  });

  es.addEventListener('point', e => {
    const d = JSON.parse(e.data);
    addMapPoint(d.point, d.current || _livePoints.length, total);
  });

  es.addEventListener('done', e => {
    const d = JSON.parse(e.data);
    const badge = document.getElementById('run-status-badge');
    document.getElementById('stop-run-btn').classList.add('hidden');
    if (d.success) {
      badge.className = 'status-badge success';
      badge.textContent = '✅ 跑步完成';
      toast('跑步任务完成！', 'success');
    } else {
      badge.className = 'status-badge failed';
      badge.textContent = '❌ 跑步失败';
      toast('跑步任务失败，查看日志', 'error');
    }
    es.close();
  });

  es.onerror = () => { es.close(); };
}

// ---- 历史记录 ----
async function loadTerms() {
  const sel = document.getElementById('term-select');
  sel.innerHTML = '<option>加载中...</option>';
  const res = await api('/api/history/terms');
  if (res.code !== 200 || !res.data.length) {
    sel.innerHTML = '<option>加载失败</option>';
    toast(res.msg || '获取学期失败', 'error');
    return;
  }
  sel.innerHTML = res.data.map(t => `<option value="${t.value}">${t.key} (${t.sjd})</option>`).join('');
  loadRuns();
}

async function loadRuns() {
  const tableName = document.getElementById('term-select').value;
  if (!tableName || tableName === '加载中...' || tableName === '加载失败') return;
  currentTableName = tableName;
  document.getElementById('runs-table-wrap').innerHTML = '<div class="text-muted">加载中...</div>';
  const res = await api(`/api/history/runs?table_name=${encodeURIComponent(tableName)}`);
  if (res.code !== 200) { toast(res.msg, 'error'); return; }
  allRuns = res.data.runs;
  renderRunsTable(res.data.groups);
  updateStats();
}

function renderRunsTable(groups) {
  if (!groups.length) {
    document.getElementById('runs-table-wrap').innerHTML = '<div class="text-muted">暂无记录</div>';
    return;
  }
  let rows = '';
  groups.forEach(g => {
    rows += `<tr class="month-row"><td colspan="6" style="padding:8px 12px">📅 ${g.month} (${g.runs.length}条)</td></tr>`;
    g.runs.forEach(run => {
      const qualified = run.isQualified !== '2' && !run.noQualifiedReason;
      const endTime = (run.recordEndTime || '').slice(11) || '-';
      rows += `<tr>
        <td><input type="checkbox" class="run-check" data-id="${run.id}"></td>
        <td>${endTime}</td>
        <td>${run.recordMileage || '-'} km</td>
        <td><span class="badge ${qualified ? 'badge-green' : 'badge-red'}">${qualified ? '✅ 合格' : '❌ 不合格'}</span></td>
        <td>
          <button class="btn btn-xs btn-outline" onclick="saveRun('${run.id}')">💾 保存</button>
          <button class="btn btn-xs btn-outline" onclick="showHistoryMap('${run.id}')">🗺️ 地图</button>
        </td>
      </tr>`;
    });
  });
  document.getElementById('runs-table-wrap').innerHTML =
    `<table class="run-table"><thead><tr><th>选择</th><th>结束时间</th><th>距离</th><th>状态</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function updateStats() {
  const qualified = allRuns.filter(r => r.isQualified !== '2' && !r.noQualifiedReason);
  const dist = qualified.reduce((s, r) => s + parseFloat(r.recordMileage || 0), 0);
  const mins = qualified.reduce((s, r) => s + parseInt(r.duration || 0), 0);
  const pct = Math.min(100, Math.round(qualified.length / 40 * 100));
  document.getElementById('stat-count').textContent = `${qualified.length} / 40`;
  document.getElementById('stat-dist').textContent = dist.toFixed(2) + ' km';
  document.getElementById('stat-time').textContent = Math.round(mins / 60) + ' 分钟';
  document.getElementById('stat-pct').textContent = pct + '%';
  document.getElementById('stat-pct').style.color = pct >= 100 ? '#10b981' : pct >= 50 ? '#f59e0b' : '#ef4444';
}

async function saveRun(runId) {
  const res = await api('/api/history/save', { method: 'POST', body: JSON.stringify({ run_id: runId, table_name: currentTableName }) });
  toast(res.msg, res.code === 200 ? 'success' : 'error');
  if (res.code === 200) { loadTaskFiles(); loadCronTaskFiles(); }
}

async function saveSelectedRuns() {
  const checked = [...document.querySelectorAll('.run-check:checked')].map(el => el.dataset.id);
  if (!checked.length) { toast('请先勾选记录', 'error'); return; }
  let ok = 0;
  for (const id of checked) {
    const res = await api('/api/history/save', { method: 'POST', body: JSON.stringify({ run_id: id, table_name: currentTableName }) });
    if (res.code === 200) ok++;
  }
  toast(`已保存 ${ok}/${checked.length} 条`, 'success');
  loadTaskFiles(); loadCronTaskFiles();
}

// ---- 定时任务 ----
async function loadCronTaskFiles() {
  const res = await api('/api/run/task_files');
  ['cron-task-file', 'once-task-file'].forEach(id => {
    const sel = document.getElementById(id);
    if (!sel) return;
    sel.innerHTML = '<option value="">-- 请选择任务文件 --</option>';
    (res.data || []).forEach(f => {
      const opt = document.createElement('option');
      opt.value = f.name;
      opt.textContent = `${f.name} (${f.mileage}km)`;
      sel.appendChild(opt);
    });
  });
}

function switchCronTab(tab) {
  document.getElementById('cron-form-repeat').style.display = tab === 'repeat' ? 'block' : 'none';
  document.getElementById('cron-form-once').style.display = tab === 'once' ? 'block' : 'none';
  document.getElementById('tab-repeat').className = tab === 'repeat' ? 'btn btn-sm btn-primary' : 'btn btn-sm btn-outline';
  document.getElementById('tab-once').className = tab === 'once' ? 'btn btn-sm btn-primary' : 'btn btn-sm btn-outline';
}

function setOnceDate(daysFromNow) {
  const d = new Date();
  d.setDate(d.getDate() + daysFromNow);
  document.getElementById('once-date').value = d.toISOString().slice(0, 10);
}

async function createOnceJob() {
  const name = document.getElementById('once-name').value.trim();
  const time = document.getElementById('once-time').value.trim();
  const date = document.getElementById('once-date').value.trim();
  const useSchoolFile = document.getElementById('once-use-school-file').checked;
  const task_file = useSchoolFile ? '' : document.getElementById('once-task-file').value;
  if (!name) { toast('请填写任务名称', 'error'); return; }
  if (!time) { toast('请设置执行时间', 'error'); return; }
  if (!date) { toast('请选择执行日期', 'error'); return; }
  if (!useSchoolFile && !task_file) { toast('请选择任务文件', 'error'); return; }
  const res = await api('/api/cron/create', {
    method: 'POST',
    body: JSON.stringify({ name, time, run_date: date, task_file, use_school_file: useSchoolFile })
  });
  toast(res.msg, res.code === 200 ? 'success' : 'error');
  if (res.code === 200) {
    document.getElementById('once-name').value = '';
    document.getElementById('once-date').value = '';
    loadCronJobs();
  }
}

function setDays(days) {
  document.querySelectorAll('.day-btn').forEach(btn => {
    btn.classList.toggle('active', days.includes(parseInt(btn.dataset.day)));
  });
}

function getSelectedDays() {
  return [...document.querySelectorAll('.day-btn.active')].map(b => parseInt(b.dataset.day));
}

document.addEventListener('click', e => {
  if (e.target.classList.contains('day-btn')) e.target.classList.toggle('active');
});

function toggleSchoolFile(prefix) {
  const checked = document.getElementById(`${prefix}-use-school-file`).checked;
  const sel = document.getElementById(`${prefix}-task-file`);
  sel.style.display = checked ? 'none' : 'block';
  sel.disabled = checked;
}

async function createCronJob() {
  const name = document.getElementById('cron-name').value.trim();
  const time = document.getElementById('cron-time').value.trim();
  const useSchoolFile = document.getElementById('cron-use-school-file').checked;
  const task_file = useSchoolFile ? '' : document.getElementById('cron-task-file').value;
  const days = getSelectedDays();
  if (!name) { toast('请填写任务名称', 'error'); return; }
  if (!time) { toast('请设置执行时间', 'error'); return; }
  if (!days.length) { toast('请至少选择一天', 'error'); return; }
  if (!useSchoolFile && !task_file) { toast('请选择任务文件', 'error'); return; }
  const res = await api('/api/cron/create', {
    method: 'POST',
    body: JSON.stringify({ name, time, days, task_file, use_school_file: useSchoolFile })
  });
  toast(res.msg, res.code === 200 ? 'success' : 'error');
  if (res.code === 200) {
    document.getElementById('cron-name').value = '';
    setDays([]);
    loadCronJobs();
  }
}

async function loadCronJobs() {
  const res = await api('/api/cron/list');
  const el = document.getElementById('cron-jobs-list');
  if (!res.data || !res.data.length) {
    el.innerHTML = '<div class="text-muted">暂无定时任务</div>';
    return;
  }
  el.innerHTML = res.data.map(job => {
    const statusColor = job.last_status === 'success' ? '#10b981' : job.last_status === 'failed' ? '#ef4444' : '#888';
    const taskName = job.use_school_file
      ? '🎲 学校随机文件（按性别）'
      : (job.task_filename || (job.task_file ? job.task_file.split(/[\\/]/).pop() : '未知'));
    const timeDesc = job.days_label
      ? (job.once ? `📅 ${job.days_label} ${job.time_label} (一次性)` : `${job.days_label} ${job.time_label}`)
      : job.cron;
    return `<div class="cron-job-item">
      <div class="cron-job-header">
        <span class="cron-job-name">${job.name}</span>
        <label class="toggle">
          <input type="checkbox" ${job.enabled ? 'checked' : ''} onchange="toggleCronJob('${job.id}')">
          <span class="toggle-slider"></span>
        </label>
      </div>
      <div class="cron-job-meta">
        ⏰ ${timeDesc} &nbsp;|&nbsp; 📁 ${taskName}<br>
        上次执行：${job.last_run || '从未'} &nbsp;
        <span style="color:${statusColor}">${job.last_status ? (job.last_status === 'success' ? '✅ 成功' : '❌ 失败') : ''}</span>
      </div>
      <div class="cron-job-actions">
        <button class="btn btn-sm btn-primary" onclick="runCronNow('${job.id}')">▶ 立即执行</button>
        <button class="btn btn-sm btn-outline" onclick="viewCronRun('${job.id}')">📊 查看详情</button>
        <button class="btn btn-sm btn-danger" onclick="deleteCronJob('${job.id}')">🗑 删除</button>
      </div>
    </div>`;
  }).join('');
}

async function toggleCronJob(id) {
  const res = await api('/api/cron/toggle', { method: 'POST', body: JSON.stringify({ job_id: id }) });
  toast(res.msg, res.code === 200 ? 'success' : 'error');
  loadCronJobs();
}

async function deleteCronJob(id) {
  if (!confirm('确认删除该定时任务？')) return;
  const res = await api('/api/cron/delete', { method: 'POST', body: JSON.stringify({ job_id: id }) });
  toast(res.msg, res.code === 200 ? 'success' : 'error');
  loadCronJobs();
}

async function runCronNow(id) {
  const res = await api('/api/cron/run_now', { method: 'POST', body: JSON.stringify({ job_id: id }) });
  toast(res.msg, res.code === 200 ? 'success' : 'error');
}

async function viewCronRun(jobId) {
  // 查当前是否有该 cron 任务正在运行或刚完成
  const res = await api('/api/run/active');
  if (res.code === 200 && res.data && res.data.cron_job_id === jobId) {
    _activeRunData = res.data;
    viewActiveRun();
    return;
  }
  // 没有实时数据，跳到日志页
  switchPage('logs');
  toast('该任务暂无实时进度，已跳转到日志页', 'info');
}

// ---- 日志 ----
async function loadLogs() {
  const res = await api('/api/logs');
  const el = document.getElementById('logs-container');
  if (!res.data || !res.data.length) {
    el.innerHTML = '<div style="color:#888">暂无日志</div>';
    return;
  }
  el.innerHTML = [...res.data].reverse().map(l => {
    const cls = l.success === true ? 'success' : l.success === false ? 'failed' : '';
    return `<div class="log-entry ${cls}"><span class="log-time">${l.time}</span><span class="log-msg">${l.msg}</span></div>`;
  }).join('');
}

// ---- 主页跑步进度轮询 ----
let _runPoller = null;
let _lastRunDone = false;
let _activeRunData = null;  // 缓存最新 active 数据

function startRunningPoller() {
  if (_runPoller) return;
  _runPoller = setInterval(async () => {
    const res = await api('/api/run/active');
    const card = document.getElementById('home-running-card');
    if (res.code !== 200 || !res.data) { card.style.display = 'none'; return; }
    const d = res.data;
    _activeRunData = d;
    card.style.display = 'block';
    const pct = d.total > 0 ? Math.round(d.current / d.total * 100) : 0;
    document.getElementById('home-run-progress-bar').style.width = pct + '%';
    document.getElementById('home-run-progress-text').textContent = `${d.current} / ${d.total} (${pct}%)`;
    const badge = document.getElementById('home-run-badge');
    const logEl = document.getElementById('home-run-last-log');
    if (d.last_log) logEl.textContent = d.last_log;
    const viewBtn = document.getElementById('home-run-view-btn');
    // 显示任务来源
    const titleEl = document.querySelector('#home-running-card h3');
    if (titleEl) titleEl.textContent = d.is_cron ? `⏰ 定时任务「${d.cron_job_name || ''}」进行中` : '🏃 跑步进行中';
    if (d.done) {
      badge.className = `status-badge ${d.success ? 'success' : 'failed'}`;
      badge.textContent = d.success ? '✅ 已完成' : '❌ 失败';
      if (viewBtn) viewBtn.textContent = '📋 查看日志';
      if (d.success && !_lastRunDone) { loadHomeStats(); }
      _lastRunDone = true;
    } else {
      badge.className = 'status-badge running';
      badge.textContent = '运行中';
      if (viewBtn) viewBtn.textContent = '📊 查看详情';
      _lastRunDone = false;
    }
  }, 3000);
}

// 点击"查看详情"跳转到跑步页并恢复地图+日志
async function viewActiveRun() {
  const d = _activeRunData;
  if (!d) return;
  switchPage('run');
  // 显示地图和日志面板
  document.getElementById('run-status').classList.remove('hidden');
  const livePanel = document.getElementById('run-live-panel');
  livePanel.style.display = 'block';
  livePanel.classList.remove('hidden');
  // 初始化地图，传入全路径预览和已上传的点数
  initRunMap(d.all_points || [], d.total || 0);
  // 恢复已上传的点（从 SSE 历史中获取）
  const badge = document.getElementById('run-status-badge');
  if (d.done) {
    badge.className = `status-badge ${d.success ? 'success' : 'failed'}`;
    badge.textContent = d.success ? '✅ 跑步完成' : '❌ 跑步失败';
  } else {
    badge.className = 'status-badge running';
    badge.textContent = '后台运行中，可关闭页面';
    _currentRunId = d.run_id;
    document.getElementById('stop-run-btn').classList.remove('hidden');
    // 重新订阅 SSE，会自动补发历史 log/point
    subscribeRunEvents(d.run_id, d.total || 0);
  }
  document.getElementById('run-progress-text').textContent =
    `进度 ${d.total > 0 ? Math.round(d.current / d.total * 100) : 0}% (${d.current}/${d.total})`;
}

// ---- 邮件通知配置 ----
async function loadEmailConfig() {
  const res = await api('/api/email/config');
  if (res.code !== 200 || !res.data) return;
  const d = res.data;
  document.getElementById('email-enable').checked = !!d.enable;
  document.getElementById('email-receiver').value = d.receiver || '';
}

function toggleEmailEnable(checkbox) {
  // 仅更新 UI，保存时一并提交
}

async function saveEmailConfig() {
  const payload = {
    enable: document.getElementById('email-enable').checked,
    receiver: document.getElementById('email-receiver').value.trim()
  };
  const res = await api('/api/email/config', { method: 'POST', body: JSON.stringify(payload) });
  toast(res.msg, res.code === 200 ? 'success' : 'error');
}

async function testEmail() {
  toast('发送中...', 'info');
  const res = await api('/api/email/test', { method: 'POST' });
  toast(res.msg, res.code === 200 ? 'success' : 'error');
}

// 启动
init();

// ---- 个人中心充值 ----
function showRechargeModal() {
  document.getElementById('rch-key').value = '';
  document.getElementById('rch-msg').className = 'msg hidden';
  document.getElementById('recharge-modal').style.display = 'flex';
}
function hideRechargeModal() {
  document.getElementById('recharge-modal').style.display = 'none';
}

async function doRecharge() {
  const btn = document.getElementById('rch-btn');
  const msgEl = document.getElementById('rch-msg');
  const key = document.getElementById('rch-key').value.trim();
  if (!key) { msgEl.textContent = '请输入卡密'; msgEl.className = 'msg error'; return; }
  btn.disabled = true; btn.textContent = '充值中...';
  try {
    const res = await api('/api/recharge', { method: 'POST', body: JSON.stringify({ key }) });
    if (res.code === 200) {
      msgEl.textContent = '✅ ' + res.msg + (res.user_time ? `，有效期至 ${res.user_time}` : '');
      msgEl.className = 'msg success';
      // 重新拉取用户信息并刷新页面显示
      const infoRes = await api('/api/user/info');
      if (infoRes.code === 200) {
        userInfo = infoRes.data;
        renderUserInfo();
      }
    } else {
      msgEl.textContent = res.msg || '充值失败';
      msgEl.className = 'msg error';
    }
  } catch (e) {
    msgEl.textContent = '请求失败: ' + e.message;
    msgEl.className = 'msg error';
  }
  btn.disabled = false; btn.textContent = '确认充值';
}

// ---- 历史记录地图弹窗 ----
async function showHistoryMap(runId) {
  const res = await api(`/api/history/detail?run_id=${runId}&table_name=${encodeURIComponent(currentTableName)}`);
  if (res.code !== 200) { toast(res.msg, 'error'); return; }
  const detail = res.data;
  const points = (detail.pointsList || []).map(p => parsePoint(p.point)).filter(Boolean);
  if (!points.length) { toast('该记录无轨迹数据', 'error'); return; }

  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9000;display:flex;align-items:center;justify-content:center';
  overlay.innerHTML = `
    <div style="background:#fff;border-radius:12px;width:700px;max-width:95vw;padding:24px;position:relative">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <b>🗺️ 跑步路径 — ${detail.recordMileage || '?'} km · ${Math.round((detail.duration||0)/60)} 分钟</b>
        <button id="close-map-btn" style="border:none;background:none;font-size:1.4rem;cursor:pointer">✕</button>
      </div>
      <div id="history-map-container" style="width:100%;height:420px;border-radius:8px"></div>
    </div>`;
  document.body.appendChild(overlay);

  overlay.querySelector('#close-map-btn').onclick = () => {
    if (window._historyMap) { window._historyMap.destroy(); window._historyMap = null; }
    overlay.remove();
  };

  setTimeout(() => {
    window._AMapSecurityConfig = { securityJsCode: window.__AMAP_SECURITY_CODE || AMAP_KEY };
    const hmap = new AMap.Map('history-map-container', { zoom: 16, mapStyle: 'amap://styles/normal' });
    window._historyMap = hmap;

    const poly = new AMap.Polyline({
      path: points, strokeColor: '#667eea', strokeWeight: 5,
      strokeOpacity: 0.9, lineJoin: 'round', lineCap: 'round'
    });
    hmap.add(poly);

    // 起点绿色标记
    hmap.add(new AMap.Marker({
      position: points[0],
      icon: new AMap.Icon({
        size: new AMap.Size(32, 40),
        image: 'data:image/svg+xml;base64,' + btoa('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="40" viewBox="0 0 32 40"><path d="M16 0C7 0 0 7 0 16C0 28 16 40 16 40S32 28 32 16C32 7 25 0 16 0Z" fill="#10b981"/><circle cx="16" cy="16" r="6" fill="white"/></svg>'),
        imageSize: new AMap.Size(32, 40)
      }), title: '起点'
    }));

    // 终点红色标记
    hmap.add(new AMap.Marker({
      position: points[points.length - 1],
      icon: new AMap.Icon({
        size: new AMap.Size(32, 40),
        image: 'data:image/svg+xml;base64,' + btoa('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="40" viewBox="0 0 32 40"><path d="M16 0C7 0 0 7 0 16C0 28 16 40 16 40S32 28 32 16C32 7 25 0 16 0Z" fill="#ef4444"/><circle cx="16" cy="16" r="6" fill="white"/></svg>'),
        imageSize: new AMap.Size(32, 40)
      }), title: '终点'
    }));

    hmap.setFitView([poly]);
  }, 100);
}
