// Supabase 集成模块 — CS2 Dashboard
var SUPABASE_URL = 'https://jenncbtyxqezdzlgqqk.supabase.co';
var SUPABASE_KEY = 'sb_publishable_UYqKWi3vy3-GfqASZawycA_Um5X1NMO';
var sb;
function initSupabase(){if(typeof supabase!=='undefined'&&!sb){sb=supabase.createClient(SUPABASE_URL,SUPABASE_KEY);}}
async function signUp(){initSupabase();var e=document.getElementById('authEmail').value.trim(),p=document.getElementById('authPass').value.trim();if(!e||!p){showMsg('请填写邮箱和密码');return;}var r=await sb.auth.signUp({email:e,password:p});if(r.error)showMsg(r.error.message);else showMsg('注册成功！请查看邮箱确认链接。');}
async function signIn(){initSupabase();var e=document.getElementById('authEmail').value.trim(),p=document.getElementById('authPass').value.trim();if(!e||!p){showMsg('请填写邮箱和密码');return;}var r=await sb.auth.signInWithPassword({email:e,password:p});if(r.error)showMsg(r.error.message);else{closeAuth();loadUserData();}}
async function signOut(){initSupabase();await sb.auth.signOut();document.getElementById('userSection').style.display='none';document.getElementById('loginBtn').style.display='';}
async function loadUserData(){initSupabase();var u=(await sb.auth.getUser()).data.user;if(!u)return;document.getElementById('loginBtn').style.display='none';document.getElementById('userSection').style.display='';document.getElementById('userEmail').textContent=u.email;}
function showMsg(m){var el=document.getElementById('authMsg');if(el){el.textContent=m;el.style.display='';setTimeout(function(){el.style.display='none';},3000);}}
function openAuth(){document.getElementById('authModal').style.display='flex';initSupabase();}
function closeAuth(){document.getElementById('authModal').style.display='none';}
(function(){if(typeof supabase!=='undefined'){initSupabase();sb.auth.onAuthStateChange(function(e,s){if(s)loadUserData();});sb.auth.getSession().then(function(r){if(r.data.session)loadUserData();});}})();
