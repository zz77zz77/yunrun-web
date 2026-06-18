async function init() {
  const [schoolRes, deviceRes] = await Promise.all([
    fetch('/api/schools').then(r => r.json()).catch(() => ({ data: [] })),
    fetch('/api/devices').then(r => r.json()).catch(() => ({ data: [] }))
  ]);
  const dl = document.getElementById('school-list');
  (schoolRes.data || []).forEach(s => {
    const opt = document.createElement('option');
    opt.value = s.schoolName;
    dl.appendChild(opt);
  });
  const sel = document.getElementById('device_name');
  (deviceRes.data || []).forEach(d => {
    const opt = document.createElement('option');
    opt.value = d; opt.textContent = d;
    sel.appendChild(opt);
  });
  const saved = JSON.parse(localStorage.getItem('login_info') || '{}');
  if (saved.username) document.getElementById('username').value = saved.username;
  if (saved.school_name) document.getElementById('school_name').value = saved.school_name;
  if (saved.device_name) {
    const opt = sel.querySelector(`option[value="${saved.device_name}"]`);
    if (opt) sel.value = saved.device_name;
  }
}

function showMsg(text, type = 'error') {
  const el = document.getElementById('msg');
  el.textContent = text;
  el.className = `msg ${type}`;
  el.classList.remove('hidden');
}

async function doLogin() {
  const btn = document.getElementById('login-btn');
  const body = {
    username: document.getElementById('username').value.trim(),
    password: document.getElementById('password').value.trim(),
    school_name: document.getElementById('school_name').value.trim(),
    device_name: document.getElementById('device_name').value
  };
  if (!body.username || !body.password || !body.school_name) {
    return showMsg('请填写完整信息');
  }
  btn.disabled = true;
  btn.textContent = '登录中...';
  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(r => r.json());
    if (res.code === 200) {
      localStorage.setItem('login_info', JSON.stringify({
        username: body.username,
        school_name: body.school_name,
        device_name: body.device_name
      }));
      showMsg('登录成功，跳转中...', 'success');
      setTimeout(() => location.href = '/', 800);
    } else {
      showMsg(res.msg || '登录失败');
      btn.disabled = false;
      btn.textContent = '登录';
    }
  } catch (e) {
    showMsg('网络错误: ' + e.message);
    btn.disabled = false;
    btn.textContent = '登录';
  }
}

document.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
init();
