const csrf = document.querySelector('#csrf').value;
const result = document.querySelector('#result');
async function send(url, data) {
  const response = await fetch(url, {method: 'POST', headers: {'Content-Type':'application/json', 'X-CSRF-Token':csrf}, body:JSON.stringify(data)});
  const text = await response.text();
  if (!response.ok) throw new Error(text);
  return JSON.parse(text);
}
function preview(text) {
  return new Promise(resolve => {
    const dialog = document.querySelector('#preview');
    dialog.querySelector('pre').textContent = text;
    dialog.showModal();
    document.querySelector('#confirm').onclick = () => {dialog.close(); resolve(true);};
    document.querySelector('#dismiss').onclick = () => {dialog.close(); resolve(false);};
    dialog.oncancel = () => resolve(false);
  });
}
document.querySelectorAll('form[data-endpoint]').forEach(form => {
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      const data = Object.fromEntries(new FormData(form));
      let payload = data;
      if (form.dataset.kind) {
        ['public','pinned','full'].forEach(key => {if (form.elements[key]) data[key] = form.elements[key].checked;});
        ['preview_images','tags','benefits','role_ids'].forEach(key => {if (key in data) data[key] = data[key].split('\n').map(x => x.trim()).filter(Boolean);});
        if (data.revision) data.revision = Number(data.revision);
        for (const key of ['starts_at','ends_at','deadline_at','published_at']) {if (data[key]) data[key] += '+09:00';}
        const notify = Boolean(data.notify), channel = data.channel_id;
        delete data.notify; delete data.channel_id;
        payload = {content:data, notify, channel_id:channel};
      } else {
        for (const key of ['starts_at','ends_at']) {if (data[key]) data[key] += '+09:00';}
      }
      const value=payload.content || payload;
      const summary=value.body || [value.title,value.description,value.starts_at && `開始：${value.starts_at}`,value.ends_at && `終了：${value.ends_at}`,value.deadline_at && `申込締切：${value.deadline_at}`,value.price_label,value.detail_url || value.purchase_url || value.booking_url,value.user_id && `ユーザー：${value.user_id} / プラン：${value.plan_id}`,value.action && `操作：${value.action}`].filter(Boolean).join('\n');
      if (!await preview(summary+(payload.notify ? '\n\nDiscord にも通知します。' : ''))) return;
      await send(form.dataset.endpoint, payload);
      result.textContent = '保存しました。通知とロール同期の結果は履歴から確認できます。';
      setTimeout(() => location.reload(), 800);
    } catch (error) {result.textContent = error.message;}
    finally {button.disabled = false;}
  });
});
const uploader = document.querySelector('#image-upload');
if (uploader) uploader.onchange = async () => {
  try {
    const file = uploader.files[0];
    if (!file || file.size > 4*1024*1024) throw new Error('4MB以下の画像を選択してください');
    const data = await new Promise((resolve,reject) => {const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});
    const saved = await send('/admin/api/upload',{data});
    const target=document.querySelector('#image-target').value;
    const field=uploader.form.elements[target];
    if (!field) throw new Error('この種類のコンテンツにプレビューはありません');
    field.value=target==='preview_images' ? [field.value.trim(),saved.url].filter(Boolean).join('\n') : saved.url;
    result.textContent = '公開カバー画像をアップロードしました。保存してください。';
  } catch (error) {result.textContent = error.message;}
};
const search=document.querySelector('#member-search');
if (search) search.oninput=()=>document.querySelectorAll('[data-user]').forEach(row=>row.hidden=!row.dataset.user.includes(search.value.trim()));
