let allUsers = [];
let currentFolder = '';
const pageTitles = { dashboard: '概览', users: '用户管理', school_files: '学校文件管理', admins: '管理员管理', keys: '密钥管理', devices: '设备管理', sysconfig: '系统设置', cron_admin: '定时任务管理', logs_admin: '运行日志', settings: '修改密码' };

async function api(url, opts = {}) {
  const res = await fetch(url, { headers: { 'Content-Type': 'application/json' }, credentials: 'include', ...opts });
  try { return await res.json(); } catch { return {}; }
}

function switchPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + name)?.classList.add('active');
  document.querySelector(`[data-page="${name}"]`)?.classList.add('active');
  document.getElementById('page-title').textContent = pageTitles[name] || name;
  if (name === 'dashboard') loadDashboard();
  if (name === 'users') loadUsers();
  if (name === 'school_files') loadSchoolFolders();
  if (name === 'admins') loadAdmins();
  if (name === 'keys') loadKeys();
  if (name === 'devices') loadDevices();
  if (name === 'sysconfig') loadSysConfig();
  if (name === 'cron_admin') loadAdminCron();
  if (name === 'logs_admin') loadAdminLogsInit();
  if (name === 'pu_admin') loadPuUsers();
}

async function init() {
  const res = await api('/admin/api/me');
  if (res.code === 401) { location.href = '/admin/login'; return; }
  document.getElementById('admin-name').textContent = '👤 ' + res.username;
  switchPage('dashboard');
}

// ---- 概览 ----
async function loadDashboard() {
  const res = await api('/admin/api/stats');
  if (res.code !== 200) {
    document.getElementById('stat-total').textContent = '错误';
    console.error('stats error:', res.msg);
    return;
  }
  document.getElementById('stat-total').textContent = res.total ?? '-';
  document.getElementById('stat-active').textContent = res.active ?? '-';
  document.getElementById('stat-expired').textContent = res.expired ?? '-';
  const tbody = document.getElementById('recent-users');
  tbody.innerHTML = (res.recent || []).map(u => `
    <tr>
      <td>${u.username}</td>
      <td>${u.school_name || '-'}</td>
      <td>${u.date || '-'}</td>
      <td>${statusBadge(u.date)}</td>
    </tr>`).join('');
}

function statusBadge(date) {
  if (!date) return '<span class="badge badge-red">无</span>';
  const now = new Date().toISOString().slice(0, 19).replace('T', ' ');
  return date > now
    ? `<span class="badge badge-green">有效</span>`
    : `<span class="badge badge-red">已过期</span>`;
}

// ---- 用户管理 ----
async function loadUsers() {
  const res = await api('/admin/api/users');
  if (res.code !== 200) return;
  allUsers = res.data || [];
  renderUsers(allUsers);
  const sel = document.getElementById('promote-user');
  sel.innerHTML = '<option value="">-- 选择用户 --</option>' +
    allUsers.map(u => `<option value="${u.username}">${u.username}（${u.school_name || ''}）</option>`).join('');
}

function filterUsers() {
  const q = document.getElementById('user-search').value.toLowerCase();
  renderUsers(allUsers.filter(u => u.username.toLowerCase().includes(q) || (u.school_name || '').toLowerCase().includes(q)));
}

function renderUsers(list) {
  const now = new Date().toISOString().slice(0, 19).replace('T', ' ');
  document.getElementById('users-table').innerHTML = list.map(u => `
    <tr>
      <td><b>${u.username}</b></td>
      <td>${u.school_name || '-'}</td>
      <td>${u.date || '-'}</td>
      <td>${statusBadge(u.date)}</td>
      <td style="max-width:150px">
        <span id="remark-text-${u.username}" style="font-size:.85rem;color:#64748b">${u.remark || ''}</span>
      </td>
      <td>
        <button class="btn btn-outline btn-xs" onclick="openExpireModal('${u.username}','${u.date || ''}')">✏️ 修改时间</button>
        <button class="btn btn-outline btn-xs" onclick="openPwdModal('${u.username}')">🔑 改密码</button>
        <button class="btn btn-outline btn-xs" onclick="openRemarkModal('${u.username}', this.dataset.remark)" data-remark="${(u.remark||'').replace(/'/g,String.fromCharCode(39))}">📝 备注</button>
        <button class="btn btn-danger btn-xs" onclick="deleteUser('${u.username}')">🗑️ 删除</button>
      </td>
    </tr>`).join('');
}

async function batchExtend() {
  const days = parseInt(document.getElementById('extend-days').value);
  if (!days || days <= 0) { alert('请输入有效天数'); return; }
  if (!confirm(`确定为所有有效期内的用户延长 ${days} 天？`)) return;
  const res = await api('/admin/api/users/batch_extend', { method: 'POST', body: JSON.stringify({ days }) });
  if (res.code === 200) {
    alert(`✅ 已为 ${res.count} 位有效用户延长 ${days} 天`);
    loadUsers();
  } else {
    alert(res.msg || '操作失败');
  }
}

function openExpireModal(username, date) {
  document.getElementById('expire-username').value = username;
  // 转换为 datetime-local 格式
  document.getElementById('expire-date').value = date ? date.replace(' ', 'T').slice(0, 16) : '';
  document.getElementById('expire-msg').className = 'msg hidden';
  document.getElementById('modal-expire').classList.add('open');
}

async function saveExpire() {
  const username = document.getElementById('expire-username').value;
  const date = document.getElementById('expire-date').value.replace('T', ' ') + ':00';
  const msgEl = document.getElementById('expire-msg');
  const res = await api('/admin/api/users/expire', { method: 'POST', body: JSON.stringify({ username, date }) });
  if (res.code === 200) {
    msgEl.textContent = '✅ 修改成功'; msgEl.className = 'msg success';
    loadUsers();
    setTimeout(() => closeModal('modal-expire'), 1000);
  } else {
    msgEl.textContent = res.msg || '修改失败'; msgEl.className = 'msg error';
  }
}

// ---- 学校文件管理 ----
async function loadSchoolFolders() {
  const res = await api('/admin/api/school_folders');
  if (res.code !== 200) return;
  const container = document.getElementById('school-folders');
  container.innerHTML = '';
  if (!res.schools || res.schools.length === 0) {
    container.innerHTML = '<p style="color:#94a3b8;text-align:center;padding:20px">暂无配置，点击右上角添加</p>';
    return;
  }
  const typeLabel = { man: '男生', woman: '女生', default: '通用' };
  res.schools.forEach(school => {
    const schoolId = 'school-' + Math.random().toString(36).slice(2);
    const div = document.createElement('div');
    div.style.marginBottom = '16px';
    div.innerHTML = `
      <div onclick="toggleCollapse('${schoolId}')" style="cursor:pointer;display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:#f1f5f9;border-radius:8px;margin-bottom:0;user-select:none">
        <span style="font-size:.95rem;font-weight:600;color:#1e293b">🏫 ${school.school_name}</span>
        <span id="${schoolId}-arrow" style="font-size:.8rem;color:#64748b;transition:transform .2s">▼</span>
      </div>
      <div id="${schoolId}" style="padding:12px 4px 0;display:block"></div>`;
    const body = div.querySelector(`#${schoolId}`);
    school.folders.forEach(folder => {
      const folderId = 'folder-' + Math.random().toString(36).slice(2);
      const folderDiv = document.createElement('div');
      folderDiv.style.marginBottom = '10px';
      folderDiv.innerHTML = `
        <div onclick="toggleCollapse('${folderId}')" style="cursor:pointer;display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:#fff;border:1px solid #e2e8f0;border-radius:6px">
          <span style="font-size:.875rem;font-weight:500">
            📁 ${folder.folder_name}
            <span class="badge badge-blue" style="margin-left:6px">${typeLabel[folder.folder_type] || folder.folder_type}</span>
            <span style="color:#94a3b8;font-size:.8rem;margin-left:6px">${folder.files.length} 个文件</span>
            ${!folder.exists ? '<span class="badge badge-red" style="margin-left:4px">不存在</span>' : ''}
          </span>
          <div class="gap-8" onclick="event.stopPropagation()">
            <button class="btn btn-primary btn-xs" onclick="openUpload('${folder.folder_name}')">📤 上传</button>
            <button class="btn btn-danger btn-xs" onclick="deleteFolderConfig('${school.school_name}','${folder.folder_type}')">🗑️ 移除</button>
            <span id="${folderId}-arrow" style="font-size:.8rem;color:#94a3b8;margin-left:4px">▼</span>
          </div>
        </div>
        <div id="${folderId}" style="display:none;padding:4px 0 0 8px">
          <ul class="file-list">
            ${folder.files.map(f => `
              <li class="file-item">
                <span>📄 ${f}</span>
                <div class="gap-8">
                  <a class="btn btn-outline btn-xs" href="/admin/api/school_files/download?folder=${encodeURIComponent(folder.folder_name)}&file=${encodeURIComponent(f)}" download="${f}">⬇️ 下载</a>
                  <button class="btn btn-danger btn-xs" onclick="deleteFile('${folder.folder_name}','${f}')">🗑️ 删除</button>
                </div>
              </li>`).join('')}
            ${folder.files.length === 0 ? '<li style="color:#94a3b8;padding:8px 12px;font-size:.85rem">暂无文件</li>' : ''}
          </ul>
        </div>`;
      body.appendChild(folderDiv);
    });
    container.appendChild(div);
  });
}

function toggleCollapse(id) {
  const el = document.getElementById(id);
  const arrow = document.getElementById(id + '-arrow');
  if (!el) return;
  const collapsed = el.style.display === 'none';
  el.style.display = collapsed ? 'block' : 'none';
  if (arrow) arrow.style.transform = collapsed ? '' : 'rotate(-90deg)';
}

async function showAddFolderModal() {
  document.getElementById('add-folder-msg').className = 'msg hidden';
  document.getElementById('folder-school').value = '';
  document.getElementById('folder-name').value = '';
  document.getElementById('folder-type').value = 'default';
  // 加载学校列表
  const res = await api('/admin/api/school_list');
  const dl = document.getElementById('school-datalist');
  dl.innerHTML = (res.data || []).map(s => `<option value="${s}">`).join('');
  document.getElementById('modal-add-folder').classList.add('open');
}

async function saveFolder() {
  const school_name = document.getElementById('folder-school').value.trim();
  const folder_type = document.getElementById('folder-type').value;
  const folder_name = document.getElementById('folder-name').value.trim();
  const msgEl = document.getElementById('add-folder-msg');
  if (!school_name || !folder_name) { msgEl.textContent = '请填写完整'; msgEl.className = 'msg error'; return; }
  const res = await api('/admin/api/school_folders/set', { method: 'POST', body: JSON.stringify({ school_name, folder_type, folder_name }) });
  if (res.code === 200) {
    msgEl.textContent = '✅ 保存成功'; msgEl.className = 'msg success';
    loadSchoolFolders();
    setTimeout(() => closeModal('modal-add-folder'), 800);
  } else {
    msgEl.textContent = res.msg || '保存失败'; msgEl.className = 'msg error';
  }
}

async function deleteFolderConfig(school_name, folder_type) {
  if (!confirm(`确定移除「${school_name}」的${folder_type}文件夹配置？（不会删除实际文件）`)) return;
  const res = await api('/admin/api/school_folders/delete', { method: 'POST', body: JSON.stringify({ school_name, folder_type }) });
  if (res.code === 200) loadSchoolFolders();
  else alert(res.msg || '操作失败');
}

function openUpload(folderName) {
  currentFolder = folderName;
  document.getElementById('upload-folder-name').textContent = folderName;
  document.getElementById('upload-msg').className = 'msg hidden';
  document.getElementById('upload-files').value = '';
  document.getElementById('modal-upload').classList.add('open');
}

async function doUpload() {
  const files = document.getElementById('upload-files').files;
  const msgEl = document.getElementById('upload-msg');
  if (!files.length) { msgEl.textContent = '请选择文件'; msgEl.className = 'msg error'; return; }
  const fd = new FormData();
  fd.append('folder', currentFolder);
  for (const f of files) fd.append('files', f);
  const res = await fetch('/admin/api/school_files/upload', { method: 'POST', body: fd, credentials: 'include' }).then(r => r.json());
  if (res.code === 200) {
    msgEl.textContent = `✅ 上传成功 ${res.count} 个文件`; msgEl.className = 'msg success';
    loadSchoolFolders();
    setTimeout(() => closeModal('modal-upload'), 1000);
  } else {
    msgEl.textContent = res.msg || '上传失败'; msgEl.className = 'msg error';
  }
}

async function deleteFile(folder, file) {
  if (!confirm(`确定删除 ${file}？`)) return;
  const res = await api('/admin/api/school_files/delete', { method: 'POST', body: JSON.stringify({ folder, file }) });
  if (res.code === 200) loadSchoolFolders();
  else alert(res.msg || '删除失败');
}

// ---- 管理员管理 ----
async function loadAdmins() {
  const res = await api('/admin/api/admins');
  if (res.code !== 200) return;
  document.getElementById('admins-table').innerHTML = (res.data || []).map(a => `
    <tr>
      <td><b>${a.username}</b></td>
      <td>${a.source || '手动创建'}</td>
      <td><button class="btn btn-danger btn-xs" onclick="deleteAdmin('${a.username}')">删除</button></td>
    </tr>`).join('');
}

function showAddAdmin() {
  document.getElementById('new-admin-user').value = '';
  document.getElementById('new-admin-pwd').value = '';
  document.getElementById('add-admin-msg').className = 'msg hidden';
  document.getElementById('modal-add-admin').classList.add('open');
}

async function addAdmin() {
  const username = document.getElementById('new-admin-user').value.trim();
  const password = document.getElementById('new-admin-pwd').value.trim();
  const msgEl = document.getElementById('add-admin-msg');
  if (!username || !password) { msgEl.textContent = '请填写完整'; msgEl.className = 'msg error'; return; }
  if (password.length < 6) { msgEl.textContent = '密码至少6位'; msgEl.className = 'msg error'; return; }
  const res = await api('/admin/api/admins/add', { method: 'POST', body: JSON.stringify({ username, password }) });
  if (res.code === 200) {
    msgEl.textContent = '✅ 添加成功'; msgEl.className = 'msg success';
    loadAdmins();
    setTimeout(() => closeModal('modal-add-admin'), 1000);
  } else {
    msgEl.textContent = res.msg || '添加失败'; msgEl.className = 'msg error';
  }
}

async function deleteAdmin(username) {
  if (!confirm(`确定删除管理员 ${username}？`)) return;
  const res = await api('/admin/api/admins/delete', { method: 'POST', body: JSON.stringify({ username }) });
  if (res.code === 200) loadAdmins();
  else alert(res.msg || '删除失败');
}

async function promoteUser() {
  const username = document.getElementById('promote-user').value;
  if (!username) { alert('请选择用户'); return; }
  const res = await api('/admin/api/admins/promote', { method: 'POST', body: JSON.stringify({ username }) });
  if (res.code === 200) { alert('已设为管理员'); loadAdmins(); }
  else alert(res.msg || '操作失败');
}

// ---- 修改密码 ----
async function changePassword() {
  const old_pwd = document.getElementById('old-pwd').value;
  const new_pwd = document.getElementById('new-pwd').value;
  const confirm_pwd = document.getElementById('confirm-pwd').value;
  const msgEl = document.getElementById('pwd-msg');
  if (!old_pwd || !new_pwd) { msgEl.textContent = '请填写完整'; msgEl.className = 'msg error'; return; }
  if (new_pwd.length < 6) { msgEl.textContent = '新密码至少6位'; msgEl.className = 'msg error'; return; }
  if (new_pwd !== confirm_pwd) { msgEl.textContent = '两次密码不一致'; msgEl.className = 'msg error'; return; }
  const res = await api('/admin/api/change_password', { method: 'POST', body: JSON.stringify({ old_pwd, new_pwd }) });
  if (res.code === 200) {
    msgEl.textContent = '✅ 修改成功'; msgEl.className = 'msg success';
    document.getElementById('old-pwd').value = '';
    document.getElementById('new-pwd').value = '';
    document.getElementById('confirm-pwd').value = '';
  } else {
    msgEl.textContent = res.msg || '修改失败'; msgEl.className = 'msg error';
  }
}

// ---- 退出 ----
async function doLogout() {
  await api('/admin/api/logout', { method: 'POST' });
  location.href = '/admin/login';
}

// ---- 工具 ----
function closeModal(id) { document.getElementById(id).classList.remove('open'); }

// ---- 密钥管理 ----
document.addEventListener('DOMContentLoaded', () => {
  const sel = document.getElementById('key-hours');
  if (sel) sel.addEventListener('change', () => {
    document.getElementById('custom-hours-wrap').style.display = sel.value === 'custom' ? 'block' : 'none';
  });
});

async function loadKeys() {
  const filter = document.getElementById('key-filter')?.value || 'all';
  const res = await api(`/admin/api/keys?filter=${filter}`);
  if (res.code !== 200) return;
  const hourLabel = h => h >= 8760 ? `${h/8760}年` : h >= 720 ? `${Math.round(h/720)}个月` : `${h}小时`;
  document.getElementById('keys-table').innerHTML = (res.data || []).map(k => `
    <tr>
      <td style="font-family:monospace;font-size:.85rem">${k.key}</td>
      <td>${hourLabel(k.time)}</td>
      <td>${k.username ? '<span class="badge badge-blue">已使用</span>' : '<span class="badge badge-green">未使用</span>'}</td>
      <td>${k.username || '-'}</td>
      <td><button class="btn btn-danger btn-xs" onclick="deleteKey('${k.key}')">🗑️ 删除</button></td>
    </tr>`).join('');
}

async function generateKeys() {
  const sel = document.getElementById('key-hours');
  const hours = sel.value === 'custom'
    ? parseInt(document.getElementById('custom-hours').value)
    : parseInt(sel.value);
  const count = parseInt(document.getElementById('key-count').value) || 1;
  if (!hours || hours <= 0) { alert('请输入有效小时数'); return; }
  const res = await api('/admin/api/keys/generate', { method: 'POST', body: JSON.stringify({ hours, count }) });
  if (res.code === 200) {
    const wrap = document.getElementById('gen-result');
    wrap.style.display = 'block';
    document.getElementById('gen-keys-text').value = res.keys.join('\n');
    loadKeys();
  } else {
    alert(res.msg || '生成失败');
  }
}

function copyKeys() {
  const ta = document.getElementById('gen-keys-text');
  ta.select();
  document.execCommand('copy');
  alert('已复制到剪贴板');
}

async function deleteKey(key) {
  if (!confirm(`确定删除卡密 ${key}？`)) return;
  const res = await api('/admin/api/keys/delete', { method: 'POST', body: JSON.stringify({ key }) });
  if (res.code === 200) loadKeys();
  else alert(res.msg || '删除失败');
}

// ---- 设备管理 ----
async function loadDevices() {
  const res = await api('/admin/api/devices');
  if (res.code !== 200) return;
  document.getElementById('devices-table').innerHTML = (res.data || []).map(d => `
    <tr>
      <td>${d.id}</td>
      <td>${d.name}</td>
      <td>
        <button class="btn btn-outline btn-xs" onclick="showEditDevice(${d.id},'${d.name.replace(/'/g,"\\'")}')">✏️ 编辑</button>
        <button class="btn btn-danger btn-xs" onclick="deleteDevice(${d.id})">🗑️ 删除</button>
      </td>
    </tr>`).join('');
}

function showAddDevice() {
  document.getElementById('device-modal-title').textContent = '➕ 添加设备';
  document.getElementById('device-id').value = '';
  document.getElementById('device-name').value = '';
  document.getElementById('device-msg').className = 'msg hidden';
  document.getElementById('modal-device').classList.add('open');
}

function showEditDevice(id, name) {
  document.getElementById('device-modal-title').textContent = '✏️ 编辑设备';
  document.getElementById('device-id').value = id;
  document.getElementById('device-name').value = name;
  document.getElementById('device-msg').className = 'msg hidden';
  document.getElementById('modal-device').classList.add('open');
}

async function saveDevice() {
  const id = document.getElementById('device-id').value;
  const name = document.getElementById('device-name').value.trim();
  const msgEl = document.getElementById('device-msg');
  if (!name) { msgEl.textContent = '请输入设备名称'; msgEl.className = 'msg error'; return; }
  const url = id ? '/admin/api/devices/update' : '/admin/api/devices/add';
  const body = id ? { id: parseInt(id), name } : { name };
  const res = await api(url, { method: 'POST', body: JSON.stringify(body) });
  if (res.code === 200) {
    msgEl.textContent = '✅ ' + res.msg; msgEl.className = 'msg success';
    loadDevices();
    setTimeout(() => closeModal('modal-device'), 800);
  } else {
    msgEl.textContent = res.msg || '操作失败'; msgEl.className = 'msg error';
  }
}

async function deleteDevice(id) {
  if (!confirm('确定删除该设备？')) return;
  const res = await api('/admin/api/devices/delete', { method: 'POST', body: JSON.stringify({ id }) });
  if (res.code === 200) loadDevices();
  else alert(res.msg || '删除失败');
}

// ---- 用户密码修改 ----
function openPwdModal(username) {
  document.getElementById('pwd-username').value = username;
  document.getElementById('pwd-new').value = '';
  document.getElementById('pwd-modal-msg').className = 'msg hidden';
  document.getElementById('modal-pwd').classList.add('open');
}

async function saveUserPwd() {
  const username = document.getElementById('pwd-username').value;
  const password = document.getElementById('pwd-new').value.trim();
  const msgEl = document.getElementById('pwd-modal-msg');
  if (!password) { msgEl.textContent = '请输入新密码'; msgEl.className = 'msg error'; return; }
  if (password.length < 6) { msgEl.textContent = '密码至少6位'; msgEl.className = 'msg error'; return; }
  const res = await api('/admin/api/users/password', { method: 'POST', body: JSON.stringify({ username, password }) });
  if (res.code === 200) {
    msgEl.textContent = '✅ 修改成功'; msgEl.className = 'msg success';
    setTimeout(() => closeModal('modal-pwd'), 800);
  } else {
    msgEl.textContent = res.msg || '修改失败'; msgEl.className = 'msg error';
  }
}

// ---- 用户备注 ----
function openRemarkModal(username, remarkOrBtn) {
  const remark = typeof remarkOrBtn === 'string' ? remarkOrBtn : (remarkOrBtn?.dataset?.remark || '');
  document.getElementById('remark-username').value = username;
  document.getElementById('remark-content').value = remark;
  document.getElementById('remark-modal-msg').className = 'msg hidden';
  document.getElementById('modal-remark').classList.add('open');
}

async function saveRemark() {
  const username = document.getElementById('remark-username').value;
  const remark = document.getElementById('remark-content').value.trim();
  const msgEl = document.getElementById('remark-modal-msg');
  const res = await api('/admin/api/users/remark', { method: 'POST', body: JSON.stringify({ username, remark }) });
  if (res.code === 200) {
    msgEl.textContent = '✅ 已保存'; msgEl.className = 'msg success';
    // 更新列表中的备注显示
    const el = document.getElementById('remark-text-' + username);
    if (el) el.textContent = remark;
    setTimeout(() => closeModal('modal-remark'), 600);
  } else {
    msgEl.textContent = res.msg || '保存失败'; msgEl.className = 'msg error';
  }
}

async function deleteUser(username) {
  if (!confirm(`确定删除用户 ${username}？\n该操作将删除用户的所有数据，不可恢复！`)) return;
  const res = await api('/admin/api/users/delete', { method: 'POST', body: JSON.stringify({ username }) });
  if (res.code === 200) {
    alert('✅ 用户已删除');
    loadUsers();
  } else {
    alert(res.msg || '删除失败');
  }
}

// ---- 系统设置 ----
async function loadSysConfig() {
  const res = await api('/admin/api/sys_config');
  if (res.code === 200) {
    document.getElementById('sysconfig-table').innerHTML = (res.data || []).map(c => `
      <tr>
        <td style="font-family:monospace;font-size:.85rem">${c.key}</td>
        <td style="color:#64748b;font-size:.85rem">${c.desc}</td>
        <td><input type="text" id="cfg-${c.key}" value="${c.value}" style="width:80px;padding:4px 8px;border:1px solid #d1d5db;border-radius:4px;font-size:.875rem"></td>
        <td><button class="btn btn-primary btn-xs" onclick="saveSysConfig('${c.key}')">保存</button></td>
      </tr>`).join('');
  }
  // 加载邮件配置
  const emRes = await api('/admin/api/email/config');
  if (emRes.code === 200 && emRes.data) {
    const d = emRes.data;
    document.getElementById('cfg-smtp-server').value = d.smtp_server || '';
    document.getElementById('cfg-smtp-port').value = d.smtp_port || '';
    document.getElementById('cfg-smtp-user').value = d.smtp_user || '';
    document.getElementById('cfg-smtp-pass').value = d.smtp_pass || '';
    document.getElementById('cfg-sender-name').value = d.sender_name || '';
  }
  // 加载地图配置
  const mapRes = await api('/admin/api/map/config');
  if (mapRes.code === 200 && mapRes.data) {
    document.getElementById('cfg-amap-key').value = mapRes.data.amap_key || '';
    document.getElementById('cfg-amap-security').value = mapRes.data.amap_security_code || '';
  }
}

async function saveSysConfig(key) {
  const value = document.getElementById('cfg-' + key)?.value.trim();
  if (!value) { alert('值不能为空'); return; }
  const res = await api('/admin/api/sys_config', { method: 'POST', body: JSON.stringify({ key, value }) });
  if (res.code === 200) alert('✅ ' + res.msg);
  else alert(res.msg || '保存失败');
}

async function saveEmailConfig() {
  const msgEl = document.getElementById('email-msg');
  const cfg = {
    smtp_server: document.getElementById('cfg-smtp-server').value.trim(),
    smtp_port: document.getElementById('cfg-smtp-port').value.trim(),
    smtp_user: document.getElementById('cfg-smtp-user').value.trim(),
    smtp_pass: document.getElementById('cfg-smtp-pass').value.trim(),
    sender_name: document.getElementById('cfg-sender-name').value.trim(),
  };
  if (!cfg.smtp_user || !cfg.smtp_pass) {
    msgEl.textContent = '❌ 发件人邮箱和授权码不能为空';
    msgEl.className = 'msg error';
    return;
  }
  const res = await api('/admin/api/email/config', { method: 'POST', body: JSON.stringify(cfg) });
  if (res.code === 200) {
    msgEl.textContent = '✅ ' + res.msg;
    msgEl.className = 'msg success';
  } else {
    msgEl.textContent = '❌ ' + (res.msg || '保存失败');
    msgEl.className = 'msg error';
  }
  setTimeout(() => { msgEl.className = 'msg hidden'; }, 3000);
}

async function testEmail() {
  const receiver = document.getElementById('cfg-test-email').value.trim();
  if (!receiver) { alert('请填写测试收件人邮箱'); return; }
  const msgEl = document.getElementById('email-msg');
  msgEl.textContent = '⏳ 发送中...';
  msgEl.className = 'msg';
  // 先保存配置再测试
  await saveEmailConfig();
  const res = await api('/admin/api/email/test', { method: 'POST', body: JSON.stringify({ receiver }) });
  if (res.code === 200) {
    msgEl.textContent = '✅ ' + res.msg;
    msgEl.className = 'msg success';
  } else {
    msgEl.textContent = '❌ ' + (res.msg || '发送失败');
    msgEl.className = 'msg error';
  }
}

async function saveMapConfig() {
  const msgEl = document.getElementById('map-msg');
  const cfg = {
    amap_key: document.getElementById('cfg-amap-key').value.trim(),
    amap_security_code: document.getElementById('cfg-amap-security').value.trim(),
  };
  if (!cfg.amap_key) {
    msgEl.textContent = '❌ 地图 Key 不能为空';
    msgEl.className = 'msg error';
    return;
  }
  const res = await api('/admin/api/map/config', { method: 'POST', body: JSON.stringify(cfg) });
  if (res.code === 200) {
    msgEl.textContent = '✅ ' + res.msg + '（刷新页面后生效）';
    msgEl.className = 'msg success';
  } else {
    msgEl.textContent = '❌ ' + (res.msg || '保存失败');
    msgEl.className = 'msg error';
  }
  setTimeout(() => { msgEl.className = 'msg hidden'; }, 3000);
}

// ---- 定时任务管理 ----
async function loadAdminCron() {
  const res = await api('/admin/api/cron/list');
  if (res.code !== 200) return;
  const jobs = res.data || [];
  document.getElementById('admin-cron-table').innerHTML = jobs.length === 0
    ? '<tr><td colspan="7" style="text-align:center;color:#94a3b8">暂无定时任务</td></tr>'
    : jobs.map(j => `
    <tr>
      <td>${j.username}</td>
      <td>${j.name}</td>
      <td>${j.days_label || ''} ${j.time_label || ''}</td>
      <td style="font-size:.8rem;color:#64748b">${j.task_filename || (j.use_school_file ? '🎲随机' : '-')}</td>
      <td>${j.enabled ? '<span class="badge badge-green">启用</span>' : '<span class="badge badge-red">禁用</span>'}</td>
      <td style="font-size:.8rem">${j.last_run || '-'}</td>
      <td>
        <button class="btn btn-outline btn-xs" onclick="adminToggleCron('${j.id}')">${j.enabled ? '禁用' : '启用'}</button>
        <button class="btn btn-danger btn-xs" onclick="adminDeleteCron('${j.id}')">删除</button>
      </td>
    </tr>`).join('');
}

async function adminToggleCron(jobId) {
  const res = await api('/admin/api/cron/toggle', { method: 'POST', body: JSON.stringify({ job_id: jobId }) });
  if (res.code === 200) loadAdminCron();
  else alert(res.msg || '操作失败');
}

async function adminDeleteCron(jobId) {
  if (!confirm('确定删除该定时任务？')) return;
  const res = await api('/admin/api/cron/delete', { method: 'POST', body: JSON.stringify({ job_id: jobId }) });
  if (res.code === 200) loadAdminCron();
  else alert(res.msg || '删除失败');
}

// ---- 运行日志 ----
async function loadAdminLogsInit() {
  const res = await api('/admin/api/users/list_simple');
  const dl = document.getElementById('log-user-datalist');
  if (dl) {
    dl.innerHTML = (res.data || []).map(u => `<option value="${u}">`).join('');
  }
  loadAdminLogs();
}

async function loadAdminLogs() {
  const username = (document.getElementById('log-user-filter')?.value || '').trim();
  const res = await api(`/admin/api/logs${username ? '?username=' + encodeURIComponent(username) : ''}`);
  if (res.code !== 200) return;
  const box = document.getElementById('admin-logs-box');
  box.innerHTML = (res.data || []).map(l => {
    const color = l.success === true ? '#a8ff78' : l.success === false ? '#ff6b6b' : '#e2e8f0';
    return `<div style="padding:2px 0;border-bottom:1px solid rgba(255,255,255,.05)">
      <span style="color:#888">${l.time || ''}</span>
      <span style="color:#667eea;margin:0 6px">[${l.username || ''}]</span>
      <span style="color:${color}">${l.msg || ''}</span>
    </div>`;
  }).join('') || '<div style="color:#888">暂无日志</div>';
}

// ---- 口袋管理 ----
let _puAllUsers = [];

async function loadPuUsers() {
  const res = await api('/admin/api/pu/users');
  if (res.code !== 200) return;
  _puAllUsers = res.data || [];
  renderPuUsers(_puAllUsers);
}

function filterPuUsers() {
  const kw = (document.getElementById('pu-search')?.value || '').toLowerCase();
  renderPuUsers(kw ? _puAllUsers.filter(u =>
    (u.yunrun_username || '').toLowerCase().includes(kw) ||
    (u.userName || '').toLowerCase().includes(kw) ||
    (u.college || '').toLowerCase().includes(kw)
  ) : _puAllUsers);
}

function renderPuUsers(list) {
  const tb = document.getElementById('pu-users-table');
  if (!tb) return;
  if (!list.length) { tb.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#94a3b8;padding:20px">暂无数据</td></tr>'; return; }
  tb.innerHTML = list.map(u => `
    <tr>
      <td>${u.yunrun_username || '—'}</td>
      <td><b>${u.userName || '—'}</b></td>
      <td>${u.college || '—'}</td>
      <td style="color:#64748b;font-size:.8rem">${u.email || '—'}</td>
      <td>
        <label style="display:inline-flex;align-items:center;gap:8px;cursor:pointer">
          <input type="checkbox" ${u.auto_scheduler ? 'checked' : ''}
            onchange="togglePuScheduler(${u.id}, this.checked, this)"
            style="width:16px;height:16px;cursor:pointer">
          <span style="font-size:.85rem;color:${u.auto_scheduler ? '#10b981' : '#94a3b8'}">${u.auto_scheduler ? '已开启' : '已关闭'}</span>
        </label>
      </td>
    </tr>`).join('');
}

async function togglePuScheduler(id, enabled, el) {
  const span = el.nextElementSibling;
  const res = await api('/admin/api/pu/users/toggle', { method: 'POST', body: JSON.stringify({ id, enabled }) });
  if (res.code !== 200) {
    el.checked = !enabled;
    alert('操作失败：' + (res.msg || ''));
    return;
  }
  if (span) { span.textContent = enabled ? '已开启' : '已关闭'; span.style.color = enabled ? '#10b981' : '#94a3b8'; }
  // 同步本地数据
  const u = _puAllUsers.find(u => u.id === id);
  if (u) u.auto_scheduler = enabled;
}

init();
