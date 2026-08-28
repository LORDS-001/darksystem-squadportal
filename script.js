const K='darkSystemV4';

// V19 backend bridge — keeps the existing UI/state model intact while moving persistence and authentication to the server.
const DARK_BACKEND = window.location.protocol.startsWith('http') && !window.location.protocol.startsWith('file');
async function api(path, options={}){
  if(!DARK_BACKEND) throw new Error('backend_unavailable');
  const r=await fetch(path,{credentials:'same-origin',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
  let data={}; try{data=await r.json()}catch(e){}
  if(!r.ok) throw new Error(data.error||'Request failed');
  return data;
}
function scrubForSyncSquad(d){
  const copy=structuredClone(d); copy.members=(copy.members||[]).map(m=>{const x={...m};delete x.password;delete x.passwordHash;delete x.resetCode;delete x.resetExpires;return x}); return copy;
}
function scrubForSyncCommunity(d){
  const copy=structuredClone(d); copy.accounts=(copy.accounts||[]).map(a=>{const x={...a};delete x.password;delete x.passwordHash;delete x.resetCode;delete x.resetExpires;return x}); return copy;
}
let backendHydrated=false;
async function backendHydrate(){
  if(!DARK_BACKEND)return;
  try{
    let data=await api('/api/bootstrap');
    const localHasData=(db.members||[]).length>5 || (db.announcements||[]).length>1 || (db.events||[]).length>0 || (communityDb.accounts||[]).length>0 || (communityDb.registrations||[]).length>0 || (communityDb.tournaments||[]).length>2;
    const serverLooksFresh=(data.squad?.members||[]).length===5 && (data.community?.accounts||[]).length===0 && (data.community?.registrations||[]).length===0;
    if(localHasData && serverLooksFresh){
      backendHydrated=true;
      await backendSync();
      data=await api('/api/bootstrap');
    }
    if(data.squad) db=normalizeDb(data.squad);
    if(data.community) communityDb=normalizeCommunity(data.community);
    backendHydrated=true;
    renderPublic();
    refreshSiteMenu();
  }catch(e){console.warn('Dark System backend unavailable; using local prototype storage.',e)}
}
async function backendSync(){
  if(!DARK_BACKEND || !backendHydrated)return;
  try{await api('/api/state',{method:'PUT',body:JSON.stringify({squad:scrubForSyncSquad(db),community:scrubForSyncCommunity(communityDb)})})}catch(e){console.warn('Backend sync failed',e)}
}
async function backendIntegrityCheck(){
  if(!DARK_BACKEND)return null;
  try{const data=await api('/api/auth/me'); return data;}catch(e){return null}
}

const seed={
  members:[
    {id:1,name:'Dark System Owner',ign:'OWNER',gameId:'000000',serverId:'0000',role:'Squad Owner',lane:'',email:'',phone:'',birthday:'',accessCode:'DS-OWNER',status:'Offline',lastLogin:null,profileComplete:true,accountActivated:true},
    {id:2,name:'Demo Leader',ign:'LEADER',gameId:'111111',serverId:'1111',role:'Squad Leader',lane:'Mid Lane',email:'',phone:'',birthday:'',accessCode:'DS-LEADER',status:'Offline',lastLogin:null,profileComplete:true,accountActivated:true},
    {id:3,name:'Demo Assistant',ign:'ASSIST',gameId:'222222',serverId:'2222',role:'Assistant Squad Leader',lane:'Roam',email:'',phone:'',birthday:'',accessCode:'DS-ASSIST',status:'Offline',lastLogin:null,profileComplete:true,accountActivated:true},
    {id:4,name:'Demo Member',ign:'MEMBER',gameId:'333333',serverId:'3333',role:'Squad Member',lane:'Gold Lane',email:'',phone:'',birthday:'',accessCode:'DS-MEMBER',status:'Offline',lastLogin:null,profileComplete:true,accountActivated:true}
    ,{id:5,name:'New Demo Member',ign:'NEWBIE',gameId:'444444',serverId:'4444',role:'Squad Member',lane:'',email:'',phone:'',birthday:'',accessCode:'SQM-DEMO1',status:'Offline',lastLogin:null,profileComplete:false,accountActivated:false}
  ],
  announcements:[{id:1,title:'Welcome to Dark System V4',body:'The squad portal is ready for testing.',author:'Dark System Owner',time:new Date().toISOString()}],
  reports:[],
  complaints:[],
  events:[],
  reportConfig:{title:'Squad Report',description:'Complete the current squad report format below.',fields:[
    {id:'reportTitle',label:'Report Title',type:'text',required:true},
    {id:'reportDetails',label:'Report Details',type:'textarea',required:true}
  ]}
};

function normalizeDb(raw){
  const d=raw||structuredClone(seed);
  d.members=(d.members||[]).map(m=>({
    ...m,
    accessCode:m.accessCode||m.code||'',
    role:m.role||'Squad Member',
    status:m.status||'Offline',
    lastLogin:m.lastLogin||null,
    profileComplete:typeof m.profileComplete==='boolean'?m.profileComplete:true,
    accountActivated:typeof m.accountActivated==='boolean'?m.accountActivated:true,
    lane:m.lane||'',
    email:m.email||'',
    phone:m.phone||'',
    birthday:m.birthday||''
  }));
  d.announcements=d.announcements||[];
  d.reports=d.reports||[];
  d.complaints=d.complaints||[];
  d.notifications=Array.isArray(d.notifications)?d.notifications:[];
  d.events=d.events||[];
  d.reportConfig=d.reportConfig||structuredClone(seed.reportConfig);
  if(!Array.isArray(d.reportConfig.fields)||!d.reportConfig.fields.length)d.reportConfig=structuredClone(seed.reportConfig);
  return d;
}
let db=normalizeDb(DARK_BACKEND ? null : JSON.parse(localStorage.getItem(K)||'null'));
// Ensure the first-time demo account exists even when an older V4/V5 localStorage database is present.
if(!db.members.some(m=>String(m.ign||'').toLowerCase()==='newbie')){
  db.members.push({id:Date.now()+5,name:'New Demo Member',ign:'NEWBIE',gameId:'444444',serverId:'4444',role:'Squad Member',lane:'',email:'',phone:'',birthday:'',accessCode:'SQM-DEMO1',status:'Offline',lastLogin:null,profileComplete:false,accountActivated:false});
}
const demo=db.members.find(m=>String(m.ign||'').toLowerCase()==='newbie');
if(demo){demo.gameId='444444';demo.serverId='4444';demo.accessCode='SQM-DEMO1';demo.role='Squad Member';demo.profileComplete=false;demo.accountActivated=false;demo.status='Offline';}
if(!DARK_BACKEND) save();
let current=null,tab='overview',presence;

function save(){const snapshot=structuredClone(db);(snapshot.members||[]).forEach(m=>{delete m.password;delete m.passwordHash;delete m.resetCode;delete m.resetExpires});if(!DARK_BACKEND) localStorage.setItem(K,JSON.stringify(snapshot)); backendSync()}

const CK='darkSystemCommunityV1';
const communitySeed={
  accounts:[],
  tournaments:[
    {id:'T1',title:'Dark System 1v1 Challenge',game:'Mobile Legends: Bang Bang',format:'1v1',date:'2026-09-05',time:'18:00',slots:32,status:'Open',reward:'Grand Prize',rules:'Standard Dark System tournament rules apply.'},
    {id:'T2',title:'Dark System Squad vs Squad',game:'Mobile Legends: Bang Bang',format:'5v5',date:'2026-09-12',time:'18:00',slots:10,status:'Open',reward:'Tournament Rewards',rules:'Teams must register with eligible players.'}
  ],
  registrations:[]
};
function normalizeCommunity(raw){
  const d=raw||structuredClone(communitySeed);
  d.accounts=(d.accounts||[]).map(a=>({...a,ign:a.ign||'',gameId:a.gameId||'',serverId:a.serverId||'',email:a.email||'',phone:a.phone||'',password:a.password||'',createdAt:a.createdAt||new Date().toISOString(),emailNotifications:a.emailNotifications!==false}));
  d.tournaments=Array.isArray(d.tournaments)?d.tournaments:structuredClone(communitySeed.tournaments);
  d.registrations=Array.isArray(d.registrations)?d.registrations:[];
  d.tournamentManagers=Array.isArray(d.tournamentManagers)?d.tournamentManagers:[];
  d.notifications=Array.isArray(d.notifications)?d.notifications:[];
  d.seasonPoints=d.seasonPoints&&typeof d.seasonPoints==='object'?d.seasonPoints:{};
  d.seasonHistory=Array.isArray(d.seasonHistory)?d.seasonHistory:[];
  d.seasonHallOfFame=Array.isArray(d.seasonHallOfFame)?d.seasonHallOfFame:[];
  d.eventParticipation=Array.isArray(d.eventParticipation)?d.eventParticipation:[];
  d.currentSeason=d.currentSeason||null;
  return d;
}
let communityDb=normalizeCommunity(DARK_BACKEND ? null : JSON.parse(localStorage.getItem(CK)||'null'));
function enforceTournamentManagerEligibility(){
  const leaderIds=new Set(db.members.filter(m=>['Squad Leader','Assistant Squad Leader'].includes(m.role)).map(m=>String(m.id)));
  communityDb.tournamentManagers=(communityDb.tournamentManagers||[]).filter(id=>leaderIds.has(String(id)));
  saveCommunity();
}
function saveCommunity(){const snapshot=structuredClone(communityDb);(snapshot.accounts||[]).forEach(a=>{delete a.password;delete a.passwordHash;delete a.resetCode;delete a.resetExpires});if(!DARK_BACKEND) localStorage.setItem(CK,JSON.stringify(snapshot)); backendSync()}
function ensureLinkedCommunityAccount(member){
  if(!member)return null;
  let a=communityDb.accounts.find(x=>String(x.squadMemberId)===String(member.id));
  if(!a){
    a={id:Date.now()+Math.floor(Math.random()*1000),squadMemberId:member.id,ign:member.ign||member.name||'',gameId:member.gameId||'',serverId:member.serverId||'',email:(member.email||`squad-${member.id}@dark.system.local`).toLowerCase(),phone:member.phone||'',password:'',role:member.role||'Squad Member',lane:member.lane||'',createdAt:new Date().toISOString(),linkedSquad:true};
    communityDb.accounts.push(a);
  }else{
    Object.assign(a,{ign:member.ign||a.ign,gameId:member.gameId||a.gameId,serverId:member.serverId||a.serverId,phone:member.phone||a.phone,role:member.role||a.role,lane:member.lane||a.lane});
  }
  member.communityAccountId=a.id;
  saveCommunity();
  return a;
}
function syncLinkedCommunityProfile(member){
  const a=ensureLinkedCommunityAccount(member); if(!a)return;
  a.ign=member.ign||a.ign; a.gameId=member.gameId||a.gameId; a.serverId=member.serverId||a.serverId; a.phone=member.phone||a.phone; a.role=member.role||a.role; a.lane=member.lane||a.lane; saveCommunity();
}
function switchToCommunity(){
  if(!current)return communityAuth();
  const m=db.members.find(x=>String(x.id)===String(current.id));
  if(!m)return error('ACCOUNT NOT FOUND','Your Squad account could not be found.');
  const a=ensureLinkedCommunityAccount(m);
  communityCurrent=a;
  m.status='Offline'; m.lastLogin=new Date().toISOString(); save();
  clearInterval(presence); current=null;
  close(); openCommunityApp(); refreshSiteMenu();
}
function switchToSquad(){
  if(!communityCurrent)return login();
  const memberId=communityCurrent.squadMemberId;
  if(!memberId)return error('NO SQUAD PROFILE','This Community account is not linked to a Squad Portal profile.');
  const m=db.members.find(x=>String(x.id)===String(memberId));
  if(!m)return error('SQUAD PROFILE NOT FOUND','Your linked Squad profile could not be found.');
  communityCurrent=null; current=m; m.status='Online'; m.lastLogin=new Date().toISOString(); save(); close(); openApp(); refreshSiteMenu();
}
if(!DARK_BACKEND) enforceTournamentManagerEligibility();
let communityCurrent=null;
function goHome(){
  document.getElementById('communityPage').classList.add('hidden');
  document.getElementById('home').classList.remove('hidden');
  window.scrollTo({top:0,behavior:'smooth'});
}
function enterCommunity(){
  document.getElementById('home').classList.add('hidden');
  document.getElementById('communityPage').classList.remove('hidden');
  renderPublic();
  window.scrollTo({top:0,behavior:'smooth'});
}
function communityAuth(){
  if(current) return switchToCommunity();
  if(communityCurrent) return error('ALREADY LOGGED IN','You are already logged in to Community. Please log out first before opening Community Login again.');
  show(`<div class="login-wrap"><div class="login-icon">DS</div><p class="eyebrow">COMMUNITY ACCOUNT</p><h2>Log in to Community</h2><p class="muted">Use the account you created for tournament registration.</p><form id="communityLoginForm" class="form"><label class="full">Email<input id="caEmail" type="email" required autocomplete="username"></label><label class="full">Password<input id="caPass" type="password" required autocomplete="current-password"></label><div class="actions"><button class="primary">Log In</button><button type="button" class="ghost" id="forgotCommunity">Forgot Password?</button></div></form><p class="muted full">New here? <button class="text-btn" type="button" id="createCommunityLink">Create an account</button></p></div>`,{lockOverlay:true});
  document.getElementById('communityLoginForm').onsubmit=async e=>{e.preventDefault();try{const data=DARK_BACKEND?await api('/api/community/login',{method:'POST',body:JSON.stringify({email:caEmail.value.trim(),password:caPass.value})}):null;const a=data?.account||(communityDb.accounts.find(x=>x.email.toLowerCase()===caEmail.value.trim().toLowerCase()&&x.password===caPass.value));if(!a)return error('ACCESS DENIED','The email or password is incorrect.');communityCurrent=a;if(DARK_BACKEND) await backendHydrate();const pending=pendingTournamentId;pendingTournamentId=null;close();if(pending)registerFromTournament(pending);else openCommunityApp()}catch(err){error('ACCESS DENIED',err.message)}};
  document.getElementById('createCommunityLink').onclick=communityRegister;
  document.getElementById('forgotCommunity').onclick=communityForgot;
}
function communityRegister(){
  show(`<div class="login-wrap"><div class="login-icon">DS</div><p class="eyebrow">CREATE ACCOUNT</p><h2>Join Dark System Community</h2><p class="muted">Your Community account is separate from the private Squad Portal account and can be used for tournament registration.</p><form id="communityRegisterForm" class="form"><label>IGN<input id="crIgn" required></label><label>Game ID<input id="crGame" required inputmode="numeric"></label><label>Server ID<input id="crServer" required inputmode="numeric"></label><label class="full">Email Address<input id="crEmail" type="email" required autocomplete="email"></label><label>Phone Number<input id="crPhone" type="tel" required></label><label class="full">Create Password<input id="crPass" type="password" minlength="6" required autocomplete="new-password"></label><label class="full">Confirm Password<input id="crPass2" type="password" minlength="6" required autocomplete="new-password"></label><div class="actions"><button class="primary">Create Account</button></div></form></div>`,{lockOverlay:true});
  document.getElementById('communityRegisterForm').onsubmit=async e=>{e.preventDefault();const email=crEmail.value.trim().toLowerCase();if(crPass.value!==crPass2.value)return error('PASSWORDS DO NOT MATCH','Please enter the same password in both fields.');try{const data=DARK_BACKEND?await api('/api/community/register',{method:'POST',body:JSON.stringify({ign:crIgn.value.trim(),gameId:crGame.value.trim(),serverId:crServer.value.trim(),email,phone:crPhone.value.trim(),password:crPass.value})}):null;const a=data?.account||{id:Date.now(),ign:crIgn.value.trim(),gameId:crGame.value.trim(),serverId:crServer.value.trim(),email,phone:crPhone.value.trim(),password:crPass.value,createdAt:new Date().toISOString()};if(!data?.account){if(communityDb.accounts.some(a=>a.email.toLowerCase()===email))return error('ACCOUNT EXISTS','An account with this email already exists.');communityDb.accounts.push(a);saveCommunity()}else{communityDb.accounts.push(a);saveCommunity()}communityCurrent=a;const pending=pendingTournamentId;pendingTournamentId=null;close();show(`<div class="setup-lock welcome-first community-welcome"><div class="welcome-modal-art"><img src="assets/mlbb/cafe-welcome.jpg" alt="Dark System community welcome artwork"><div class="welcome-art-label">COMMUNITY</div></div><div class="welcome-modal-copy"><div class="setup-icon">✓</div><p class="eyebrow">ACCOUNT CREATED</p><h2>Welcome, ${esc(a.ign)}!</h2><p class="muted">Your community account is ready. You can now use this same profile to register for open tournaments and events.</p><div class="notice"><b>Your Community profile is active.</b><br><span>Keep your game ID, server ID and contact details current so tournament registration stays accurate.</span></div><div class="actions"><button type="button" class="primary" id="continueCommunityBtn">${pending?'Continue to Registration':'Continue to Community'}</button></div></div></div>`);const btn=document.getElementById('continueCommunityBtn');if(btn)btn.onclick=()=>{close();if(pending){registerFromTournament(pending)}else{openCommunityApp()}}}catch(err){error('ACCOUNT CREATION FAILED',err.message)}};
}
async function sendSystemEmail(to, subject, html, text){
  // Real delivery requires a server-side email endpoint/provider. The static site
  // never exposes SMTP/API secrets in the browser. Configure this endpoint on
  // deployment as window.DARK_SYSTEM_EMAIL_API.
  const endpoint = window.DARK_SYSTEM_EMAIL_API;
  if(!endpoint) return {queued:false, reason:"email_endpoint_not_configured"};
  try{
    const r=await fetch(endpoint,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({to,subject,html,text})});
    return {queued:r.ok,reason:r.ok?"sent":"email_provider_error"};
  }catch(e){ return {queued:false,reason:"email_network_error"}; }
}

async function emailNotificationTo(account, title, message){
  if(!account || !account.email || account.emailNotifications===false) return;
  await sendSystemEmail(account.email, `Dark System: ${title}`, `<h2>${esc(title)}</h2><p>${esc(message)}</p><p>Log in to Dark System to view the full notification.</p>`, `${title}\n\n${message}\n\nLog in to Dark System to view the full notification.`);
}

function communityForgot(){
  show(`<div class="login-wrap"><div class="login-icon">?</div><p class="eyebrow">PASSWORD RECOVERY</p><h2>Forgot Password?</h2><p class="muted">Enter the email on your Community account. A one-time reset code will be sent to that email.</p><form id="forgotForm" class="form"><label class="full">Email Address<input id="fpEmail" type="email" required autocomplete="email"></label><div class="actions"><button class="primary">Send Reset Code</button><button type="button" class="ghost" id="forgotCancel">Cancel</button></div></form></div>`);
  document.getElementById('forgotCancel').onclick=()=>close();
  document.getElementById('forgotForm').onsubmit=async e=>{
    e.preventDefault();
    const email=fpEmail.value.trim().toLowerCase();
    if(DARK_BACKEND){try{await api('/api/community/forgot',{method:'POST',body:JSON.stringify({email})});show(`<div class="login-wrap"><p class="eyebrow">RESET CODE SENT</p><h2>Check Your Email</h2><p class="muted">If that Community account exists and email delivery is configured, a reset code has been sent.</p><form id="resetForm" class="form"><label>Reset Code<input id="resetCode" required inputmode="numeric" autocomplete="one-time-code"></label><label class="full">New Password<input id="newPass" type="password" minlength="6" required autocomplete="new-password"></label><label class="full">Confirm New Password<input id="newPass2" type="password" minlength="6" required autocomplete="new-password"></label><div class="actions"><button class="primary">Reset Password</button><button type="button" class="ghost" id="resetCancel">Cancel</button></div></form></div>`);document.getElementById('resetCancel').onclick=()=>close();document.getElementById('resetForm').onsubmit=async x=>{x.preventDefault();if(newPass.value!==newPass2.value)return error('PASSWORDS DO NOT MATCH','Enter the same new password in both fields.');try{await api('/api/community/reset',{method:'POST',body:JSON.stringify({email,code:resetCode.value.trim(),password:newPass.value})});show(`<div class="setup-lock"><div class="setup-icon">✓</div><h2>Password Updated</h2><p class="muted">Your Community password has been changed successfully.</p><div class="actions"><button class="primary" id="backToLoginAfterReset">Back to Login</button></div></div>`);document.getElementById('backToLoginAfterReset').onclick=()=>{close();communityAuth();}}catch(err){error('INVALID CODE',err.message)}};}catch(err){error('RECOVERY ERROR',err.message)}return;}
    const a=communityDb.accounts.find(x=>x.email.toLowerCase()===email);
    if(!a) return error('ACCOUNT NOT FOUND','No Community account was found for that email address.');
    const code=String(Math.floor(100000+Math.random()*900000));
    a.resetCode=code;a.resetExpires=Date.now()+10*60*1000;saveCommunity();
    const result=await sendSystemEmail(a.email,'Your Dark System password reset code',`<p>Your Dark System password reset code is:</p><h1 style="letter-spacing:6px">${code}</h1><p>This code expires in 10 minutes.</p>`,`Your Dark System password reset code is ${code}. It expires in 10 minutes.`);
    show(`<div class="login-wrap"><p class="eyebrow">RESET CODE SENT</p><h2>Check Your Email</h2><p class="muted">If email delivery is configured, the reset code has been sent to <b>${esc(a.email)}</b>. Enter the code below.</p>${result.queued?'':'<div class="notice warning"><b>Email delivery is not configured on this site yet.</b><br>Connect a server-side email provider to deliver the code automatically.</div>'}<form id="resetForm" class="form"><label>Reset Code<input id="resetCode" required inputmode="numeric" autocomplete="one-time-code"></label><label class="full">New Password<input id="newPass" type="password" minlength="6" required autocomplete="new-password"></label><label class="full">Confirm New Password<input id="newPass2" type="password" minlength="6" required autocomplete="new-password"></label><div class="actions"><button class="primary">Reset Password</button><button type="button" class="ghost" id="resetCancel">Cancel</button></div></form></div>`);
    document.getElementById('resetCancel').onclick=()=>close();
    document.getElementById('resetForm').onsubmit=x=>{
      x.preventDefault();
      if(newPass.value!==newPass2.value)return error('PASSWORDS DO NOT MATCH','Enter the same new password in both fields.');
      if(resetCode.value.trim()!==String(a.resetCode)||Date.now()>a.resetExpires)return error('INVALID CODE','The reset code is invalid or expired.');
      a.password=newPass.value;a.resetCode='';a.resetExpires=null;saveCommunity();
      show(`<div class="setup-lock"><div class="setup-icon">✓</div><h2>Password Updated</h2><p class="muted">Your Community password has been changed successfully.</p><div class="actions"><button class="primary" id="backToLoginAfterReset">Back to Login</button></div></div>`);
      document.getElementById('backToLoginAfterReset').onclick=()=>{close();communityAuth();};
    };
  };
}

function openCommunityApp(){
  document.getElementById('public').classList.add('hidden');document.querySelector('footer').classList.add('hidden');document.getElementById('app').classList.add('hidden');document.getElementById('communityApp').classList.remove('hidden');renderCommunityApp();window.scrollTo(0,0);
}
function communityLogout(){if(DARK_BACKEND)api('/api/logout',{method:'POST'}).catch(()=>{});communityCurrent=null;refreshSiteMenu();document.getElementById('communityApp').classList.add('hidden');document.getElementById('public').classList.remove('hidden');document.querySelector('footer').classList.remove('hidden');renderPublic();goHome()}
function renderCommunityApp(){
  const regs=communityDb.registrations.filter(r=>r.accountId===communityCurrent.id);
  const open=communityDb.tournaments.filter(t=>isTournamentVisibleInAvailable(t));
  document.getElementById('communityApp').innerHTML=`<div class="community-dashboard"><header class="community-dash-head"><div><span class="eyebrow">COMMUNITY DASHBOARD</span><h1>Welcome, ${esc(communityCurrent.ign)}</h1><p class="muted">Browse available tournaments here; registration is completed inside the Tournament Center.</p></div><div class="community-user"><b>${esc(communityCurrent.ign)}</b><small>${esc(communityCurrent.email)}</small><button class="small notification-tool" onclick="toggleNotificationBar()">🔔 Notifications <span class="notification-count">${(communityDb.notifications||[]).filter(n=>!n.read&&(!n.audienceId||(communityCurrent&&String(n.audienceId)===String(communityCurrent.id)))).length}</span></button>${communityCurrent?.squadMemberId?'<button class="small accent" onclick="switchToSquad()">Switch to Squad</button>':''}<button class="small" onclick="communityLogout()">Log Out</button></div></header><div class="community-dash-grid"><section class="panel community-profile-panel"><div class="section-head"><div><span class="eyebrow">YOUR PROFILE</span><h2>Registration Profile</h2></div><button class="small accent" onclick="editCommunityProfile()">Edit Profile</button></div><div class="profile-data"><div><small>IGN</small><b>${esc(communityCurrent.ign)}</b></div><div><small>Game ID</small><b>${esc(communityCurrent.gameId)}</b></div><div><small>Server ID</small><b>${esc(communityCurrent.serverId)}</b></div><div><small>Email</small><b>${esc(communityCurrent.email)}</b></div><div><small>Phone</small><b>${esc(communityCurrent.phone)}</b></div></div></section><section class="panel"><div class="section-head"><div><span class="eyebrow">YOUR TOURNAMENTS</span><h2>Registrations</h2></div></div>${regs.map(r=>{const t=communityDb.tournaments.find(x=>x.id===r.tournamentId);return t?`<div class="registration-row"><b>${esc(t.title)}</b><span>${esc(r.status||'Registered')}</span></div>`:''}).join('')||'<p class="muted">You have not registered for a tournament yet.</p>'}</section></div><section class="panel community-tournaments-panel"><div class="section-head"><div><span class="eyebrow">OPEN NOW</span><h2>Available Tournaments</h2><p class="muted">Open a tournament to view its full page and register there.</p></div></div><div class="community-event-grid">${open.map(t=>{const registered=regs.some(r=>r.tournamentId===t.id);return `<article class="community-event-card"><span class="tour-status">${esc(t.status.toUpperCase())}</span><div class="tour-icon">⚔</div><h3>${esc(t.title)}</h3><p>${esc(t.game)} • ${esc(t.format)}</p><div class="event-public-meta"><span>📅 ${esc(t.date)}</span><span>⏰ ${esc(t.time)}</span><span>👥 ${esc(t.slots)} slots</span></div><button class="small accent" onclick="openTournamentPage();setTimeout(()=>tourDetails('${t.id}'),0)">${registered?'View Tournament • Registered':'View Tournament'}</button></article>`}).join('')||'<p class="muted">No tournaments are open for registration right now.</p>'}</div></section></div>`;
}
function editCommunityProfile(){show(`<div class="login-wrap"><p class="eyebrow">COMMUNITY PROFILE</p><h2>Edit Profile</h2><form id="cep" class="form"><label>IGN<input id="epIgn" required value="${esc(communityCurrent.ign)}"></label><label>Game ID<input id="epGame" required value="${esc(communityCurrent.gameId)}"></label><label>Server ID<input id="epServer" required value="${esc(communityCurrent.serverId)}"></label><label class="full">Email<input id="epEmail" type="email" required value="${esc(communityCurrent.email)}"></label><label class="full">Phone Number<input id="epPhone" type="tel" required value="${esc(communityCurrent.phone)}"></label><div class="actions"><button class="primary">Save Profile</button></div></form></div>`);document.getElementById('cep').onsubmit=async e=>{e.preventDefault();const payload={ign:epIgn.value.trim(),gameId:epGame.value.trim(),serverId:epServer.value.trim(),email:epEmail.value.trim().toLowerCase(),phone:epPhone.value.trim()};try{if(DARK_BACKEND){const data=await api('/api/community/profile',{method:'PUT',body:JSON.stringify(payload)});if(data.account)communityCurrent=data.account;}else{Object.assign(communityCurrent,payload);saveCommunity()}close();renderCommunityApp()}catch(err){error('PROFILE UPDATE FAILED',err.message)}}}
async function registerCommunityTournament(id){const t=communityDb.tournaments.find(x=>x.id===id);if(!t||t.status!=='Open')return error('REGISTRATION CLOSED','This tournament is not currently open.');if(communityDb.registrations.some(r=>r.accountId===communityCurrent.id&&r.tournamentId===id))return error('ALREADY REGISTERED','You are already registered for this tournament.');try{if(DARK_BACKEND){const data=await api('/api/tournaments/register',{method:'POST',body:JSON.stringify({tournamentId:String(id)})});if(Array.isArray(data.registrations))communityDb.registrations=data.registrations;}else{communityDb.registrations.push({id:Date.now(),accountId:communityCurrent.id,tournamentId:id,status:'Registered',registeredAt:new Date().toISOString()});saveCommunity()}show(`<div class="setup-lock"><div class="setup-icon">✓</div><p class="eyebrow">REGISTRATION COMPLETE</p><h2>${esc(t.title)}</h2><p class="muted">You are registered using your community profile.</p><div class="actions"><button class="primary" onclick="close();renderCommunityApp()">Done</button></div></div>`)}catch(err){error('REGISTRATION FAILED',err.message)}}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]))}
function ini(s){return String(s||'?').trim().split(/\s+/).map(x=>x[0]).join('').slice(0,2).toUpperCase()}
function rank(r){return {'Squad Owner':4,'Squad Leader':3,'Assistant Squad Leader':2,'Squad Member':1}[r]||0}
function isOwner(){return current?.role==='Squad Owner'}
function isLeader(){return rank(current?.role)>=3}
function fmt(x){return x?new Date(x).toLocaleString([], {dateStyle:'medium',timeStyle:'short'}):'Never'}
function dateOnly(x){if(!x)return '';return new Date(`${x}T00:00:00`).toLocaleDateString([], {dateStyle:'medium'})}
function laneIcon(l){return ({'EXP':'⚔','Mid':'◆','Jungle':'♜','Roam':'🛡','Gold':'◈'})[l]||'•'}
function codeForRole(role){const prefix=role==='Squad Member'?'SQM':role==='Assistant Squad Leader'?'SQA':role==='Squad Leader'?'SQL':'';return prefix?prefix+'-'+Math.random().toString(36).slice(2,7).toUpperCase():'FREE'}
function code(){return codeForRole('Squad Member')}
function show(html,opts={}){const modal=document.getElementById('modal');document.getElementById('modalBody').innerHTML=html;modal.classList.toggle('setup-mode',!!opts.setup);modal.classList.toggle('lock-overlay',!!opts.lockOverlay);modal.classList.add('open')}
function close(){document.getElementById('modal').classList.remove('open','setup-mode','lock-overlay')}
function error(t,b){show(`<p class="eyebrow">DARK SYSTEM</p><h2>${esc(t)}</h2><p class="muted">${esc(b)}</p>`)}

document.getElementById('close').onclick=close;
document.getElementById('modal').onclick=e=>{if(e.target.id==='modal'&&!e.target.closest('.setup-lock')&&!document.getElementById('modal').classList.contains('lock-overlay'))close()};
document.getElementById('year').textContent=new Date().getFullYear();
function toggleSiteMenu(force){
  const menu=document.getElementById('siteMenu');
  const btn=document.getElementById('menu');
  if(!menu)return;
  const open=typeof force==='boolean'?force:!menu.classList.contains('open');
  menu.classList.toggle('open',open);
  menu.setAttribute('aria-hidden',String(!open));
  if(btn)btn.setAttribute('aria-expanded',String(open));
  refreshSiteMenu();
}
function refreshSiteMenu(){
  const state=document.getElementById('menuSessionState');
  const switchBtn=document.getElementById('menuSwitchPortal');
  if(!state)return;
  if(current){
    state.textContent=`Squad Portal • ${current.ign}`;
    if(switchBtn){switchBtn.style.display='inline-flex';switchBtn.textContent='↔ Switch to Community';}
  }else if(communityCurrent){
    state.textContent=`Community • ${communityCurrent.ign}`;
    if(switchBtn){switchBtn.style.display='inline-flex';switchBtn.textContent='↔ Switch to Squad';}
  }else{
    state.textContent='Guest mode';
    if(switchBtn)switchBtn.style.display='none';
  }
}
function menuGo(target){
  toggleSiteMenu(false);
  if(target==='home'){goHome();return;}
  if(target==='community'){
    if(current){switchToCommunity();return;}
    if(communityCurrent){openCommunityApp();return;}
    enterCommunity();return;
  }
  if(target==='switch'){if(current){switchToCommunity();return;} if(communityCurrent){switchToSquad();return;} return show('<p class="eyebrow">SWITCH PORTAL</p><h2>Sign in first</h2><p class="muted">Log in to a portal to switch between Community and Squad.</p>');}
  if(target==='tournaments'){openTournamentPage();return;}
  if(target==='notifications'){
    if(communityCurrent){openCommunityApp();setTimeout(toggleNotificationBar,0);return;}
    if(current){openApp();setTimeout(()=>toggleSquadNotificationBar(),0);return;}
    return show('<p class="eyebrow">NOTIFICATIONS</p><h2>Sign in to view notifications</h2><p class="muted">Log in to the Community or Squad Portal to see your personal tournament and account updates.</p>');
  }
  if(target==='profile'){
    if(current){openApp();setTimeout(()=>profile(current.id),0);return;}
    if(communityCurrent){openCommunityApp();setTimeout(editCommunityProfile,0);return;}
    return show('<p class="eyebrow">PROFILE</p><h2>Sign in to view your profile</h2><p class="muted">Your profile is available after you enter a portal.</p>');
  }
  if(target==='members'){
    showCommunityMembers();
    return;
  }
  if(target==='settings'){
    if(current){openApp();setTimeout(()=>settings(),0);return;}
    if(communityCurrent){openCommunityApp();setTimeout(editCommunityProfile,0);return;}
    return show('<p class="eyebrow">SETTINGS</p><h2>Portal settings</h2><p class="muted">Sign in to manage your account settings.</p>');
  }
  if(target==='logout'){
    if(current){logout();return;}
    if(communityCurrent){communityLogout();return;}
  }
}
document.getElementById('menu').onclick=()=>toggleSiteMenu();
document.getElementById('menuClose').onclick=()=>toggleSiteMenu(false);
document.addEventListener('click',e=>{const menu=document.getElementById('siteMenu'),btn=document.getElementById('menu');if(menu?.classList.contains('open')&&!menu.contains(e.target)&&e.target!==btn)toggleSiteMenu(false);});
document.getElementById('loginBtn').onclick=login;
document.getElementById('heroLogin').onclick=login;
document.getElementById('communityLoginBtn').onclick=communityAuth;
document.getElementById('heroCommunity').onclick=enterCommunity;
document.getElementById('communityRegister').onclick=communityRegister;
document.getElementById('communityLoginHero').onclick=communityAuth;

function login(){
  if(communityCurrent) return switchToSquad();
  if(current) return error('SQUAD PORTAL ACTIVE','You are already logged in to the Squad Portal. Please log out first before opening the Squad Portal login again.');
  show(`<div class="login-wrap"><div class="login-icon">DS</div><p class="eyebrow">RESTRICTED ACCESS</p><h2>Enter Squad Portal</h2><p class="muted">Use the details given to you by Dark System leadership.</p><form id="lf" class="form"><label>In-Game Name<input id="li" required autocomplete="username"></label><label>Game ID<input id="lg" required inputmode="numeric"></label><label>Server ID<input id="ls" required inputmode="numeric"></label><label class="full">Access Code<input id="lc" type="password" required autocomplete="current-password"></label><div class="actions"><button class="primary">Verify & Enter</button></div></form></div>`,{lockOverlay:true});
  document.getElementById('lf').onsubmit=async e=>{
    e.preventDefault();
    try{
      const data=DARK_BACKEND?await api('/api/squad/login',{method:'POST',body:JSON.stringify({ign:li.value.trim(),gameId:lg.value.trim(),serverId:ls.value.trim(),accessCode:lc.value.trim()})}):null;
      const m=data?.member||(db.members.find(x=>x.ign.toLowerCase()===li.value.trim().toLowerCase()&&String(x.gameId).trim()===lg.value.trim()&&String(x.serverId).trim()===ls.value.trim()&&String(x.accessCode).trim().toUpperCase()===lc.value.trim().toUpperCase()&&x.status!=='Disabled'));
      if(!m)return error('ACCESS DENIED','The In-Game Name, IDs or access code were not recognized.');
      if(data?.member){db.members=db.members.map(x=>String(x.id)===String(m.id)?m:x);if(!db.members.some(x=>String(x.id)===String(m.id)))db.members.push(m);}
      current=m;
      if(DARK_BACKEND) await backendHydrate();
      m=db.members.find(x=>String(x.id)===String(current.id))||m; current=m;
    }catch(err){return error('ACCESS DENIED',err.message)}
    syncLinkedCommunityProfile(m);
    if(!m.accountActivated){
      m.accountActivated=true;
      m.status='Online';
      m.lastLogin=new Date().toISOString();
      save();
      showFirstTimeWelcome();
      return;
    }
    m.lastLogin=new Date().toISOString(); m.status='Online'; save(); close(); openApp();
  };
}

function showFirstTimeWelcome(){
  show(`<div class="setup-lock welcome-first"><div class="welcome-modal-art"><img src="assets/mlbb/ice-archer.jpg" alt="Dark System hero artwork"><div class="welcome-art-label">DARK SYSTEM</div></div><div class="welcome-modal-copy"><div class="setup-icon">✓</div><span class="eyebrow">ACCOUNT CREATED</span><h2>Welcome, ${esc(current.ign)}!</h2><p class="muted">Your squad account has been created successfully. Before you can access the Squad Dashboard, you must update your profile.</p><div class="notice"><b>Profile setup is required.</b><br><span>You cannot skip this step. Your Squad Role was assigned by the Owner and cannot be changed here.</span></div><div class="actions"><button class="primary" id="continueProfile">Continue to Profile Setup</button></div></div></div>`,{setup:true});
  document.getElementById('continueProfile').onclick=showProfileSetup;
}

function openApp(){
  document.getElementById('public').classList.add('hidden'); document.querySelector('footer').classList.add('hidden'); document.getElementById('app').classList.remove('hidden'); window.scrollTo(0,0);
  if(!current.profileComplete){showProfileSetup();return;}
  render(); startPresence();
}
function startPresence(){clearInterval(presence);presence=setInterval(()=>{if(!current)return;const m=db.members.find(x=>x.id===current.id);if(m){m.status='Online';save();if(tab==='overview')render();}},10000)}
function logout(){if(DARK_BACKEND)api('/api/logout',{method:'POST'}).catch(()=>{});clearInterval(presence);if(current){const m=db.members.find(x=>x.id===current.id);if(m){m.status='Offline';save()}}current=null;refreshSiteMenu();document.getElementById('app').classList.add('hidden');document.getElementById('public').classList.remove('hidden');document.querySelector('footer').classList.remove('hidden');renderPublic();window.scrollTo(0,0)}

function renderPublic(){
  const publicMembers=communityDb.accounts;
  const publicProfiles=document.getElementById('publicProfiles'); if(publicProfiles) publicProfiles.innerHTML=publicMembers.map(m=>`<article class="card"><div class="avatar">${ini(m.ign||m.name)}</div><h3>${esc(m.ign||m.name)}</h3><p>${esc(m.role)}</p><span class="lane">${laneIcon(m.lane)} ${esc(m.lane||'Lane not set')}</span></article>`).join('')||'<p class="muted">Community profiles will appear here as members complete their profiles.</p>';
  document.getElementById('publicAnnouncements').innerHTML=db.announcements.slice().reverse().map(a=>`<article class="community-news"><small>${fmt(a.time)} • ${esc(a.author)}</small><h3>${esc(a.title)}</h3><p>${esc(a.body)}</p></article>`).join('')||'<p class="muted">No community announcements yet.</p>';
  const events=db.events.slice().filter(e=>e.date&&new Date(`${e.date}T${e.time||'23:59'}`)>=new Date()).sort((a,b)=>`${a.date}${a.time||''}`.localeCompare(`${b.date}${b.time||''}`)).slice(0,6);
  document.getElementById('publicEvents').innerHTML=events.map(e=>{const d=new Date(`${e.date}T00:00`);return `<article class="community-event-card"><div class="community-event-date"><b>${d.getDate()}</b><small>${d.toLocaleDateString([], {month:'short'}).toUpperCase()}</small></div><h3>${esc(e.title)}</h3><p>${esc(e.details||e.description||'Community event.')} </p><div class="event-public-meta"><span>⏰ ${esc(e.time||'Time TBA')}</span><span>⚡ Dark System</span></div><button class="small accent" onclick="recordEventParticipation(${e.id})">${communityCurrent?'Record Participation':'Join / Record Participation'}</button></article>`}).join('')||'<div class="empty-state"><b>No public events yet.</b><p>New community events will appear here when published.</p></div>';
  const mc=document.getElementById('communityMemberCount'); if(mc)mc.textContent=communityDb.accounts.length;
  const ec=document.getElementById('communityEventCount'); if(ec)ec.textContent=communityDb.tournaments.filter(t=>t.status==='Open').length;
  const ac=document.getElementById('communityAnnouncementCount'); if(ac)ac.textContent=db.announcements.length;
}
function showCommunityMembers(){
  const members=communityDb.accounts||[];
  const cards=members.map(m=>`<article class="card"><div class="avatar">${ini(m.ign||m.name)}</div><h3>${esc(m.ign||m.name)}</h3><p>${esc(m.role||'Community Member')}</p><span class="lane">${laneIcon(m.lane)} ${esc(m.lane||'Lane not set')}</span></article>`).join('')||'<p class="muted">No public community members yet.</p>';
  show(`<div class="login-wrap community-members-modal"><p class="eyebrow">DARK SYSTEM COMMUNITY</p><h2>Community <em>Members.</em></h2><p class="muted">Public member identities only. Private account information stays protected.</p><div class="cards community-members" style="margin-top:18px">${cards}</div><div class="actions"><button type="button" class="ghost" onclick="close()">Close</button></div></div>`);
}
function joinCommunity(type='community'){
  const title=type==='tournament'?'Show Interest':'Apply to Join Dark System';
  const text=type==='tournament'?'Leave your details and leadership can follow up when the tournament opens.':'Submit a simple community application. This does not create a private Squad Portal account.';
  show(`<div class="login-wrap"><div class="login-icon">DS</div><p class="eyebrow">COMMUNITY</p><h2>${title}</h2><p class="muted">${text}</p><form id="jf" class="form"><label>IGN<input id="ji" required></label><label>Phone Number<input id="jp" required inputmode="tel"></label><label class="full">Why do you want to join?<textarea id="jr" required placeholder="Tell Dark System a little about yourself..."></textarea></label><div class="actions"><button class="primary">Submit Application</button></div></form></div>`);
  document.getElementById('jf').onsubmit=e=>{e.preventDefault();close();show(`<div class="setup-lock"><div class="setup-icon">✓</div><p class="eyebrow">APPLICATION RECEIVED</p><h2>Thanks, ${esc(document.getElementById('ji').value)}.</h2><p class="muted">Your community interest has been recorded for this prototype. Squad Portal access is still controlled by Dark System leadership.</p><div class="actions"><button class="primary" onclick="close()">Done</button></div></div>`)};
}
saveCommunity();
renderPublic();
backendHydrate();

function render(){
  if(!current)return;
  const owner=isOwner(),leader=isLeader();
  const nav=[['overview','Overview','⌂'],['management','Management','⚙'],['announcements','Announcements','!'],['reports','Reports','▤'],['complaints','Complaints','◌'],['events','Events','◇']];
  document.getElementById('app').innerHTML=`
  <div class="app-shell">
    <aside class="sidebar">
      <div class="side-brand"><div class="side-logo">DS</div><div><b>DARK SYSTEM</b><small>SQUAD PORTAL</small></div></div>
      <div class="side-label">WORKSPACE</div>
      <div class="side-nav">${nav.map(n=>`<button class="side-link ${tab===n[0]?'active':''}" onclick="tab='${n[0]}';render()"><span>${n[2]}</span>${n[1]}${n[0]==='complaints'&&db.complaints.length?`<i>${db.complaints.length}</i>`:''}</button>`).join('')}</div>
      <div class="side-spacer"></div>
      <div class="side-user"><div class="mini-avatar">${ini(current.name)}</div><div><b>${esc(current.name)}</b><small>${esc(current.role)}</small></div></div>
      <button class="side-link portal-switch-link" onclick="switchToCommunity()"><span>↔</span>Switch to Community</button>
      <button class="side-link logout-link" onclick="logout()"><span>↪</span>Log Out</button>
    </aside>
    <main class="workspace">
      <header class="dash-top"><div><span class="mobile-kicker">PRIVATE SQUAD DASHBOARD</span><h1>${tab==='overview'?'Squad Overview':tab[0].toUpperCase()+tab.slice(1)}</h1><p class="muted">Everything you need to manage and participate in Dark System.</p></div><div class="welcome-user"><button class="small notification-tool" onclick="toggleSquadNotificationBar()">🔔 Notifications <span class="notification-count">${(db.notifications||[]).filter(n=>!n.read&&(n.audienceId==null||String(n.audienceId)===String(current.id))).length}</span></button><button class="small accent" onclick="switchToCommunity()">Switch to Community</button><div class="avatar small-avatar">${ini(current.name)}</div><div><b>Welcome, ${esc(current.name)}</b><small>${esc(current.role)} <span class="status-pill"><span class="dot on"></span> Online</span></small></div></div></header>
      ${tab==='overview'?overview(owner,leader):content(owner,leader)}
    </main>
  </div>`;
}

function overview(owner,leader){
  const myReports=db.reports.filter(r=>r.memberId===current.id).length;
  const upcoming=db.events.filter(e=>new Date(`${e.date}T${e.time||'23:59'}`)>=new Date()).sort((a,b)=>`${a.date}${a.time||''}`.localeCompare(`${b.date}${b.time||''}`)).slice(0,3);
  return `<div class="overview-grid">
    <section class="welcome-panel"><div><span class="eyebrow">PRIVATE SQUAD SPACE</span><h2>Welcome back, ${esc(current.name.split(' ')[0])}.</h2><p>You're signed in as <b>${esc(current.role)}</b>. Your status is <span class="online-text">● Online</span>.</p><div class="quick-actions"><button class="primary" onclick="tab='reports';render()">Submit Report</button><button class="small" onclick="tab='events';render()">View Events</button><button class="small" onclick="profile(${current.id})">My Profile</button></div></div><div class="welcome-mark">DS</div><div class="welcome-hero-art"><img src="assets/mlbb/neon-warrior.jpg" alt="Dark System squad hero artwork"><span>ENTER THE BATTLE</span></div></section>
    <div class="stats modern-stats"><div class="stat"><span class="stat-icon">◎</span><small>MEMBERS</small><b>${db.members.length}</b></div><div class="stat"><span class="stat-icon">◈</span><small>ONLINE</small><b>${db.members.filter(m=>m.status==='Online').length}</b></div><div class="stat"><span class="stat-icon">▤</span><small>MY REPORTS</small><b>${myReports}</b></div><div class="stat"><span class="stat-icon">◇</span><small>EVENTS</small><b>${db.events.length}</b></div></div>
    <div class="overview-cols"><section class="panel"><div class="section-head"><div><span class="eyebrow">LATEST</span><h3>Announcements</h3></div><button class="text-btn" onclick="tab='announcements';render()">View all →</button></div>${db.announcements.slice().reverse().slice(0,3).map(a=>`<div class="feed-item"><span class="feed-dot"></span><div><small>${fmt(a.time)} • ${esc(a.author)}</small><h4>${esc(a.title)}</h4><p>${esc(a.body)}</p></div></div>`).join('')||'<p class="muted">No announcements yet.</p>'}</section>
    <section class="panel"><div class="section-head"><div><span class="eyebrow">NEXT UP</span><h3>Upcoming Events</h3></div><button class="text-btn" onclick="tab='events';render()">View all →</button></div>${upcoming.map(e=>`<div class="event-mini"><div class="date-box"><b>${new Date(`${e.date}T00:00`).getDate()}</b><small>${new Date(`${e.date}T00:00`).toLocaleDateString([], {month:'short'})}</small></div><div><h4>${esc(e.title)}</h4><p>${esc(e.time||'Time TBA')} ${e.rules?`• ${esc(e.rules)}`:''}</p></div></div>`).join('')||'<p class="muted">No upcoming events.</p>'}</section></div>
    <section class="panel dashboard-guide"><span class="eyebrow">YOUR SPACE</span><h3>Dashboard at a glance</h3><div class="guide-grid"><div><b>Profile</b><p>Keep your squad identity and game details current.</p></div><div><b>Announcements</b><p>Stay updated with important squad communication.</p></div><div><b>Reports</b><p>Submit your reports using the current squad format.</p></div><div><b>Complaints</b><p>Send private concerns to squad leadership.</p></div></div></section>
  </div>`;
}

function content(owner,leader){
  if(tab==='profiles'||tab==='management')return management(owner,leader);
  if(tab==='announcements')return announcements(leader);
  if(tab==='reports')return reports(owner);
  if(tab==='complaints')return complaints();
  if(tab==='events')return events(leader);
  return overview(owner,leader);
}

function management(owner,leader){
  const canManageRoles=!!leader;
  return `<section class="panel"><div class="section-head"><div><span class="eyebrow">SQUAD MANAGEMENT</span><h2>Management</h2><p class="muted">View squad member profiles and change squad roles according to your authority. Personal member information is private and cannot be edited by leadership.</p></div>${leader?'<button class="small accent" onclick="member()">+ Add Member</button>':''}</div><div class="member-grid">${db.members.map(m=>{const isSelf=m.id===current.id;const canRole=canManageRoles&&!isSelf&&(owner?m.role!=='Squad Owner':['Squad Member','Assistant Squad Leader'].includes(m.role));return `<article class="member-card"><div class="member-card-top"><div class="avatar">${ini(m.name)}</div><span class="status-chip"><span class="dot ${m.status==='Online'?'on':''}"></span>${m.status}</span></div><h3>${esc(m.name)}</h3><p class="role-line">${esc(m.role)}</p><div class="member-ids"><span>IGN <b>${esc(m.ign)}</b></span><span>ID <b>${esc(m.gameId)}</b></span><span>Server <b>${esc(m.serverId)}</b></span><span>Lane <b>${esc(m.lane||'Not set')}</b></span><span>Last Login <b>${esc(fmt(m.lastLogin))}</b></span></div><div class="member-actions"><button class="small" onclick="profile(${m.id})">View</button>${isSelf?'<button class="small" onclick="profile('+m.id+',true)">Edit My Profile</button>':''}${canRole?`<button class="small accent" onclick="roleMenu(${m.id})">Role</button>`:''}</div></article>`;}).join('')}</div><div class="notice" style="margin-top:18px"><b>Privacy & authority</b><br><span>Leadership can view member profiles but cannot edit another member's personal information. Squad Leaders can promote Members to Assistant and demote Assistants to Member. The Squad Owner can change the role of any non-owner member. No leadership role can change their own role here.</span></div></section>`;
}

function announcements(manage){return `<div class="two-col"><section class="panel"><div class="section-head"><div><span class="eyebrow">COMMUNICATION</span><h2>Announcements</h2></div>${manage?'<button class="small accent" onclick="announce()">+ New Announcement</button>':''}</div>${db.announcements.slice().reverse().map(a=>`<article class="announcement-card"><small>${fmt(a.time)} • ${esc(a.author)}</small><h3>${esc(a.title)}</h3><p>${esc(a.body)}</p></article>`).join('')||'<p class="muted">No announcements yet.</p>'}</section><section class="panel"><span class="eyebrow">DEVICE</span><h3>Notifications</h3><p class="muted">Enable browser notifications on this device for new squad announcements.</p><button class="small accent" onclick="notifyPermission()">Enable Notifications</button></section></div>`}

function reports(owner){
  const mine=db.reports.filter(r=>r.memberId===current.id).slice().reverse();
  return `<div class="two-col reports-layout"><section class="panel"><div class="section-head"><div><span class="eyebrow">ACCOUNTABILITY</span><h2>Reports</h2><p class="muted">${esc(db.reportConfig.description||'Complete the current squad report format.')}</p></div><button class="small accent" onclick="report()">+ Submit Report</button></div>${mine.map(r=>reportCard(r)).join('')||'<div class="empty-state"><b>No reports yet.</b><p>Your submitted reports will appear here.</p></div>'}</section><section class="panel report-format-panel"><span class="eyebrow">CURRENT FORMAT</span><h3>${esc(db.reportConfig.title||'Squad Report')}</h3><p class="muted">${db.reportConfig.fields.length} field${db.reportConfig.fields.length===1?'':'s'} • ${db.reportConfig.fields.filter(f=>f.required).length} required</p><div class="format-list">${db.reportConfig.fields.map((f,i)=>`<div><span>${i+1}</span><b>${esc(f.label)}</b><small>${esc(f.type)}${f.required?' • required':''}</small></div>`).join('')}</div>${owner?'<button class="small accent full-btn" onclick="reportSettings()">⚙ Manage Report Format</button>':''}</section>${owner?`<section class="panel full-span"><div class="section-head"><div><span class="eyebrow">OWNER VIEW</span><h3>All Submitted Reports</h3></div></div>${db.reports.slice().reverse().map(reportCard).join('')||'<p class="muted">No reports submitted yet.</p>'}</section>`:''}</div>`;
}

function reportCard(r){
  const m=db.members.find(x=>x.id===r.memberId);
  const values=r.values||{};
  const body=Object.entries(values).filter(([k])=>!['reportTitle','reportDetails'].includes(k)).map(([k,v])=>{const f=db.reportConfig.fields.find(x=>x.id===k);return f&&v!==''?`<div class="report-field"><small>${esc(f.label)}</small><p>${esc(v)}</p></div>`:''}).join('');
  return `<article class="report"><div class="report-meta"><div><b>${esc(m?.name||'Unknown')}</b><span>${esc(m?.ign||'')}</span><span>${esc(m?.role||'')}</span></div><small>${fmt(r.time)}</small></div><h3>${esc(values.reportTitle||r.title||'Report')}</h3><p>${esc(values.reportDetails||r.body||'')}</p>${body}${(r.files||[]).map(f=>`<span class="attach">📎 ${esc(f.name)}</span>`).join('')}</article>`;
}

function complaints(){
  const access=isLeader();
  if(!access)return `<section class="panel narrow-panel"><span class="eyebrow">PRIVATE FEEDBACK</span><h2>Complaints</h2><p class="muted">Send a private complaint to squad leadership. Only leadership can review and respond.</p><button class="small accent" onclick="complaint()">Lodge Complaint</button></section>`;
  return `<section class="panel"><div class="section-head"><div><span class="eyebrow">LEADERSHIP ONLY</span><h2>Complaints</h2><p class="muted">Private member complaints are visible to leadership.</p></div></div>${db.complaints.slice().reverse().map(c=>{let m=db.members.find(x=>x.id===c.memberId);return `<article class="complaint"><div class="report-meta"><div><b>${esc(m?.name||'Unknown')}</b><span>${esc(m?.ign||'')}</span><span>${esc(m?.role||'')}</span></div><small>${fmt(c.time)}</small></div><h3>${esc(c.title)}</h3><p>${esc(c.body)}</p>${(c.files||[]).map(f=>`<span class="attach">📎 ${esc(f.name)}</span>`).join('')}${c.response?`<div class="reply"><b>Response — ${esc(c.respondedBy)}</b><br>${esc(c.response)}</div>`:''}<div class="card-actions"><button class="small" onclick="respond(${c.id})">${c.response?'Edit Response':'Respond'}</button></div></article>`}).join('')||'<div class="empty-state"><b>No complaints.</b><p>Nothing needs your attention right now.</p></div>'}</section>`;
}

function events(manage){
  const list=db.events.slice().sort((a,b)=>`${a.date}${a.time||''}`.localeCompare(`${b.date}${b.time||''}`));
  return `<section class="panel"><div class="section-head"><div><span class="eyebrow">SQUAD CALENDAR</span><h2>Events</h2><p class="muted">Upcoming squad activities and their rules.</p></div>${manage?'<button class="small accent" onclick="eventForm()">+ Add Event</button>':''}</div><div class="event-list">${list.map(e=>`<article class="event-card"><div class="event-date"><b>${new Date(`${e.date}T00:00`).getDate()}</b><small>${new Date(`${e.date}T00:00`).toLocaleDateString([], {month:'short',year:'numeric'})}</small></div><div class="event-main"><div class="event-heading"><div><h3>${esc(e.title)}</h3><p>${dateOnly(e.date)} • ${esc(e.time||'Time TBA')}</p></div>${manage?`<div><button class="small" onclick="eventForm(${e.id})">Edit</button> <button class="small danger" onclick="removeEvent(${e.id})">Delete</button></div>`:''}</div>${e.rules?`<div class="event-rules"><b>Rules</b><p>${esc(e.rules)}</p></div>`:''}${e.body?`<p class="event-details">${esc(e.body)}</p>`:''}</div></article>`).join('')||'<div class="empty-state"><b>No events yet.</b><p>Squad events added by leadership will appear here.</p></div>'}</div></section>`;
}

function profile(id,edit=false){
  const m=db.members.find(x=>x.id===id); if(!m)return;
  if(edit && m.id!==current.id)return error('ACCESS DENIED','Member profiles are personal. You can only edit your own profile.');
  if(edit){editProfile(m);return;}
  show(`<p class="eyebrow">SQUAD MEMBER PROFILE</p><div class="profile"><div class="avatar profile-avatar">${ini(m.name)}</div><div><div class="profile-title"><div><h2>${esc(m.name)}</h2><p class="muted">${esc(m.role)} • <span class="status-pill"><span class="dot ${m.status==='Online'?'on':''}"></span>${esc(m.status)}</span></p></div>${m.id===current.id?`<button class="small accent" onclick="close();profile(${m.id},true)">Edit My Profile</button>`:''}</div><div class="details"><div class="detail"><small>IN-GAME NAME (IGN)</small><b>${esc(m.ign)}</b></div><div class="detail"><small>GAME ID</small><b>${esc(m.gameId)}</b></div><div class="detail"><small>SERVER ID</small><b>${esc(m.serverId)}</b></div><div class="detail"><small>LANE</small><b>${esc(m.lane||'Not set')}</b></div><div class="detail"><small>SQUAD ROLE</small><b>${esc(m.role)}</b></div><div class="detail"><small>LAST LOGIN</small><b>${fmt(m.lastLogin)}</b></div><div class="detail"><small>STATUS</small><b>${esc(m.status)}</b></div><div class="detail"><small>PHONE NUMBER</small><b>${esc(m.phone||'Not set')}</b></div><div class="detail"><small>EMAIL</small><b>${esc(m.email||'Not set')}</b></div><div class="detail"><small>BIRTHDAY</small><b>${m.birthday?dateOnly(m.birthday):'Not set'}</b></div></div></div></div>`);
}

function editProfile(m){
  const owner=isOwner();
  show(`<p class="eyebrow">PROFILE SETTINGS</p><h2>Edit ${m.id===current.id?'Your':'Member'} Profile</h2><p class="muted">Keep your squad identity and game details up to date.</p><form id="pf" class="form"><label>Name<input id="pn" required value="${esc(m.name)}"></label><label>In-Game Name<input id="pi" required value="${esc(m.ign)}"></label><label>Game ID<input id="pg" required value="${esc(m.gameId)}"></label><label>Server ID<input id="ps" required value="${esc(m.serverId)}"></label><label>Email Address<input id="pe" type="email" value="${esc(m.email||'')}"></label><label>Phone Number<input id="pp" type="tel" value="${esc(m.phone||'')}"></label><label>Lane<select id="pl"><option value="">Select lane</option><option>EXP Lane</option><option>Mid Lane</option><option>Jungle</option><option>Roam</option><option>Gold Lane</option></select></label><label>Birthday<input id="pb" type="date" value="${esc(m.birthday||'')}"></label><div class="actions"><button class="primary">Save Profile</button></div></form>`);
  document.getElementById('pl').value=m.lane||'';
  document.getElementById('pf').onsubmit=e=>{e.preventDefault();Object.assign(m,{name:pn.value.trim(),ign:pi.value.trim(),gameId:pg.value.trim(),serverId:ps.value.trim(),email:pe.value.trim(),phone:pp.value.trim(),lane:pl.value,birthday:pb.value,profileComplete:true});save();current=db.members.find(x=>x.id===current.id);close();render();renderPublic()};
}

function showProfileSetup(){
  show(`<div class=\"setup-lock\"><div class=\"setup-icon\">DS</div><span class=\"eyebrow\">PROFILE SETUP — REQUIRED</span><h2>Update your profile</h2><p class=\"muted\">This step cannot be skipped. Complete your profile before entering the Squad Dashboard. Your Squad Role is assigned by the Owner and cannot be changed here.</p><form id=\"setupForm\" class=\"form\"><label>IGN (In-Game Name)<input id=\"si\" required value=\"${esc(current.ign)}\"></label><label>Game ID<input id=\"sg\" required inputmode=\"numeric\" value=\"${esc(current.gameId)}\"></label><label>Server ID<input id=\"ss\" required inputmode=\"numeric\" value=\"${esc(current.serverId)}\"></label><label>Lane<select id=\"sl\" required><option value=\"\">Select lane</option><option>EXP Lane</option><option>Mid Lane</option><option>Jungle</option><option>Roam</option><option>Gold Lane</option></select></label><label>Squad Role<select id=\"sr\" disabled><option>${esc(current.role)}</option></select></label><label>Email Address<input id=\"se\" type=\"email\" required></label><label>Phone Number<input id=\"sp\" type=\"tel\" required></label><label>Birthday<input id=\"sb\" type=\"date\" required></label><label class=\"full\">Enter Access Code to Confirm<input id=\"sc\" type=\"password\" required autocomplete=\"current-password\"></label><div class=\"actions\"><button class=\"primary\">Confirm & Update Profile</button></div></form></div>`,{setup:true});
  document.getElementById('setupForm').onsubmit=async e=>{
    e.preventDefault();
    if(sc.value.trim()!==current.accessCode){
      current=null; close(); document.getElementById('app').classList.add('hidden'); document.getElementById('public').classList.remove('hidden'); document.querySelector('footer').classList.remove('hidden'); renderPublic();
      return error('ACCESS DENIED','The access code is incorrect. Your session has been ended and you have been logged out.');
    }
    Object.assign(current,{ign:si.value.trim(),gameId:sg.value.trim(),serverId:ss.value.trim(),lane:sl.value,email:se.value.trim(),phone:sp.value.trim(),birthday:sb.value,profileComplete:true,accountActivated:true,status:'Online',lastLogin:new Date().toISOString()});
    if(DARK_BACKEND){try{const data=await api('/api/squad/profile',{method:'PUT',body:JSON.stringify({ign:current.ign,gameId:current.gameId,serverId:current.serverId,lane:current.lane,email:current.email,phone:current.phone,birthday:current.birthday,accessCode:sc.value.trim()})});if(data.member)current=data.member}catch(err){return error('PROFILE UPDATE FAILED',err.message)}}
    save();
    // Completing the mandatory first-time profile setup unlocks the private Squad Dashboard.
    document.getElementById('public').classList.add('hidden');
    document.querySelector('footer').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');
    close();
    render();
    startPresence();
  };
  document.getElementById('sl').value=current.lane||'';
}

function member(id){
  const leader=isLeader(), owner=isOwner();
  if(!leader)return error('LEADERSHIP ONLY','Only the Squad Owner or Squad Leader can add or manage squad members.');
  const editing=!!id;
  const m=id?db.members.find(x=>x.id===id):{id:Date.now(),name:'',ign:'',gameId:'',serverId:'',role:'Squad Member',accessCode:'',status:'Offline',lastLogin:null,profileComplete:false,accountActivated:false,lane:'',email:'',phone:'',birthday:''};
  if(id && !m)return error('NOT FOUND','That member could not be found.');
  if(editing && !owner && m.id!==current.id && m.role!=='Squad Member')return error('ACCESS DENIED','A Squad Leader can manage Squad Member accounts, but cannot edit leadership accounts.');
  const roleOptions=owner?'<option>Squad Member</option><option>Assistant Squad Leader</option><option>Squad Leader</option>':'<option>Squad Member</option>';
  show(`<p class=\"eyebrow\">${owner?'OWNER / LEADERSHIP CONTROL':'SQUAD LEADER CONTROL'}</p><h2>${editing?'Edit Member':'Add New Member'}</h2><p class=\"muted\">${editing?'Update the member record below.':'The member must be added here before they can enter the Squad Portal. Generate an access code and send it to the member. They will use it with the assigned IGN, Game ID and Server ID on their first login.'}</p><form id=\"mf\" class=\"form\"><label>IGN (In-Game Name)<input id=\"mi\" required value=\"${esc(m.ign)}\"></label><label>Game ID<input id=\"mg\" required inputmode=\"numeric\" value=\"${esc(m.gameId)}\"></label><label>Server ID<input id=\"ms\" required inputmode=\"numeric\" value=\"${esc(m.serverId)}\"></label><label>Squad Role<select id=\"mr\" required>${roleOptions}</select></label><label class=\"full\">Access Code<input id=\"mc\" readonly value=\"${esc(m.accessCode||'Not generated')}\"></label><div class=\"actions\"><button type=\"button\" class=\"small accent\" id=\"generateCode\">${editing?'Regenerate Access Code':'Generate Access Code'}</button><button type=\"submit\" class=\"primary\" id=\"saveMember\" ${!m.accessCode?'disabled':''}>${editing?'Save Changes':'Add Member'}</button></div></form>`);
  document.getElementById('mr').value=m.role==='Squad Owner'?'Squad Member':m.role;
  document.getElementById('generateCode').onclick=()=>{m.role=mr.value;const generated=codeForRole(m.role);m.accessCode=generated;mc.value=generated;document.getElementById('saveMember').disabled=false;};
  document.getElementById('mf').onsubmit=async e=>{e.preventDefault();if(!m.accessCode)return error('GENERATE ACCESS CODE','Generate the access code before adding this member.');const ign=mi.value.trim();Object.assign(m,{name:m.name||ign,ign,gameId:mg.value.trim(),serverId:ms.value.trim(),role:mr.value,accountActivated:m.accountActivated||false,profileComplete:m.profileComplete||false});try{if(DARK_BACKEND){const payload={name:m.name,ign:m.ign,gameId:m.gameId,serverId:m.serverId,role:m.role,accessCode:m.accessCode,lane:m.lane||'',email:m.email||'',phone:m.phone||'',birthday:m.birthday||'',profileComplete:m.profileComplete,accountActivated:m.accountActivated};const data=editing?await api('/api/squad/members',{method:'PUT',body:JSON.stringify({...payload,id:String(m.id)})}):await api('/api/squad/members',{method:'POST',body:JSON.stringify(payload)});if(data.member){if(editing)db.members=db.members.map(x=>String(x.id)===String(m.id)?data.member:x);else db.members.push(data.member);m=editing?data.member:data.member;}}else{if(editing)db.members=db.members.map(x=>x.id===m.id?m:x);else db.members.push(m);}}catch(err){return error('MEMBER SAVE FAILED',err.message)}save();close();render();renderPublic();showAccessCodeCard(m, editing?'Access code updated':'Member added successfully');
  };
}
function showAccessCodeCard(m,title){
  show(`<div class=\"setup-lock\"><div class=\"setup-icon\">✓</div><span class=\"eyebrow\">MEMBER ACCESS</span><h2>${esc(title)}</h2><p class=\"muted\">${esc(m.ign)} is now registered in the squad. Send the following access details to the member. They cannot create a Squad Portal account by themselves.</p><div class=\"notice\"><b>Access Code: ${esc(m.accessCode)}</b><br><span>IGN: ${esc(m.ign)} • Game ID: ${esc(m.gameId)} • Server ID: ${esc(m.serverId)}</span></div><div class=\"actions\"><button class=\"primary\" id=\"copyMemberCode\">Copy Access Details</button><button class=\"small\" id=\"shareMemberCode\">Share</button><button class=\"ghost\" onclick=\"close();render()\">Done</button></div></div>`);
  const details=`Dark System Squad Portal access\nIGN: ${m.ign}\nGame ID: ${m.gameId}\nServer ID: ${m.serverId}\nAccess Code: ${m.accessCode}\n\nOn first login, you must complete the compulsory profile update before entering the dashboard.`;
  document.getElementById('copyMemberCode').onclick=async()=>{try{await navigator.clipboard.writeText(details);document.getElementById('copyMemberCode').textContent='✓ Copied';}catch(e){error('COPY FAILED',details)}};
  document.getElementById('shareMemberCode').onclick=async()=>{if(navigator.share){try{await navigator.share({title:'Dark System Squad Portal Access',text:details})}catch(e){}}else{try{await navigator.clipboard.writeText(details);document.getElementById('shareMemberCode').textContent='✓ Copied';}catch(e){error('SHARE NOT AVAILABLE',details)}}};
}

function roleMenu(id){
  const m=db.members.find(x=>x.id===id); if(!m)return error('NOT FOUND','Member not found.');
  if(m.id===current.id)return error('NOT ALLOWED','You cannot change your own squad role here.');
  if(!isLeader())return error('LEADERSHIP ONLY','Only squad leadership can change squad roles.');
  const allowed=isOwner()?['Squad Member','Assistant Squad Leader','Squad Leader']:['Squad Member','Assistant Squad Leader'];
  if(!isOwner()&&!['Squad Member','Assistant Squad Leader'].includes(m.role))return error('ACCESS DENIED','A Squad Leader can only change the role of a Squad Member or Assistant Squad Leader.');
  show(`<div class="login-wrap"><span class="eyebrow">SQUAD MANAGEMENT</span><h2>Change Role</h2><p class="muted">Choose the new squad role for <b>${esc(m.ign)}</b>. The selected role becomes their new role immediately.</p><div class="profile-data"><div><small>CURRENT ROLE</small><b>${esc(m.role)}</b></div></div><form id="roleChangeForm" class="form"><label class="full">New Squad Role<select id="newRole">${allowed.map(r=>`<option ${r===m.role?'selected':''}>${r}</option>`).join('')}</select></label><div class="actions"><button class="primary">Change Role</button><button type="button" class="ghost" onclick="close()">Cancel</button></div></form></div>`);
  document.getElementById('roleChangeForm').onsubmit=e=>{e.preventDefault();applyRoleChange(m.id,document.getElementById('newRole').value)};
}
async function applyRoleChange(id,targetRole){
  if(!isLeader())return error('LEADERSHIP ONLY','Only squad leadership can change squad roles.');
  const m=db.members.find(x=>x.id===id); if(!m)return error('NOT FOUND','Member not found.');
  if(m.id===current.id)return error('NOT ALLOWED','You cannot change your own squad role here.');
  const allowed=isOwner()?['Squad Member','Assistant Squad Leader','Squad Leader']:['Squad Member','Assistant Squad Leader'];
  if(!allowed.includes(targetRole))return error('ACCESS DENIED','That role is not available to your authority level.');
  if(!isOwner()&&!['Squad Member','Assistant Squad Leader'].includes(m.role))return error('ACCESS DENIED','A Squad Leader cannot change the role of a Squad Leader.');
  const oldRole=m.role;if(oldRole===targetRole)return close();try{if(DARK_BACKEND){const data=await api('/api/squad/role',{method:'POST',body:JSON.stringify({memberId:String(m.id),role:targetRole})});if(data.member)m=data.member;}else m.role=targetRole;}catch(err){return error('ROLE UPDATE FAILED',err.message)}syncLinkedCommunityProfile(m);
  if(oldRole==='Squad Leader'&&targetRole!=='Squad Leader')communityDb.tournamentManagers=(communityDb.tournamentManagers||[]).filter(x=>String(x)!==String(m.id));
  save();enforceTournamentManagerEligibility();saveCommunity();addSquadNotification('role','Squad role updated',`Your squad role changed from ${oldRole} to ${targetRole}.`,m.id);addCommunityNotification('role','Squad role updated',`${m.ign}'s squad role changed from ${oldRole} to ${targetRole}.`,String(m.id));saveCommunity();close();render();renderPublic();
  show(`<div class="setup-lock"><div class="setup-icon">✓</div><span class="eyebrow">ROLE UPDATED</span><h2>${esc(m.ign)}</h2><p class="muted">Role changed from <b>${esc(oldRole)}</b> to <b>${esc(targetRole)}</b>. A notification has been sent to the member.</p><div class="actions"><button class="primary" onclick="close();render()">Done</button></div></div>`);
}

async function removeMember(id){if(!isOwner())return error('OWNER ONLY','Only the Squad Owner can remove members.');if(confirm('Remove this member?')){try{if(DARK_BACKEND)await api('/api/squad/members',{method:'DELETE',body:JSON.stringify({id:String(id)})});db.members=db.members.filter(m=>String(m.id)!==String(id));db.__deletedMemberIds=db.__deletedMemberIds||[];db.__deletedMemberIds.push(id);save();render();renderPublic()}catch(err){error('REMOVE FAILED',err.message)}}}

function announce(){if(!isLeader())return error('LEADERSHIP ONLY','Only squad leadership can publish announcements.');show(`<p class="eyebrow">LEADERSHIP</p><h2>New Announcement</h2><form id="af" class="form"><label class="full">Title<input id="at" required></label><label class="full">Announcement<textarea id="ab" required></textarea></label><div class="actions"><button class="primary">Publish Announcement</button></div></form>`);document.getElementById('af').onsubmit=e=>{e.preventDefault();const title=at.value.trim(),text=ab.value.trim();db.announcements.push({id:Date.now(),title,body:text,author:current.name,time:new Date().toISOString()});save();close();render();renderPublic();sendNotification(title,text)}}
async function notifyPermission(){if(!('Notification'in window))return error('NOT SUPPORTED','This browser does not support notifications.');const p=await Notification.requestPermission();if(p==='granted')new Notification('Dark System',{body:'Notifications are now enabled on this browser.'});render()}
function sendNotification(title,body){if('Notification'in window&&Notification.permission==='granted')new Notification('Dark System — '+title,{body})}

function report(){
  const fields=db.reportConfig.fields;
  show(`<p class="eyebrow">${esc(db.reportConfig.title||'SQUAD REPORT')}</p><h2>Submit Report</h2><p class="muted">Your profile and submission time are attached automatically.</p><form id="rf" class="form">${fields.map(f=>fieldInput(f)).join('')}<label class="full">Attach picture/video/file<input id="rfiles" type="file" multiple accept="image/*,video/*,.pdf,.doc,.docx"></label><div class="actions"><button class="primary">Submit Report</button></div></form>`);
  document.getElementById('rf').onsubmit=e=>{e.preventDefault();const values={};for(const f of fields){const el=document.getElementById('field_'+f.id);if(f.required&&!String(el.value).trim())return error('MISSING FIELD',`${f.label} is required.`);values[f.id]=el.value.trim()}db.reports.push({id:Date.now(),memberId:current.id,values,title:values.reportTitle||db.reportConfig.title,body:values.reportDetails||'',time:new Date().toISOString(),files:[...rfiles.files].map(f=>({name:f.name,type:f.type,size:f.size}))});save();close();render()};
}
function fieldInput(f){const req=f.required?'required':'';if(f.type==='textarea')return `<label class="full">${esc(f.label)}${f.required?' *':''}<textarea id="field_${esc(f.id)}" ${req}></textarea></label>`;if(f.type==='date'||f.type==='number')return `<label>${esc(f.label)}${f.required?' *':''}<input id="field_${esc(f.id)}" type="${f.type}" ${req}></label>`;if(f.type==='select')return `<label>${esc(f.label)}${f.required?' *':''}<select id="field_${esc(f.id)}" ${req}><option value="">Select...</option>${(f.options||[]).map(o=>`<option>${esc(o)}</option>`).join('')}</select></label>`;return `<label>${esc(f.label)}${f.required?' *':''}<input id="field_${esc(f.id)}" ${req}></label>`}

function reportSettings(){
  if(!isOwner())return error('OWNER ONLY','Only the Squad Owner can change the report format.');
  show(`<p class="eyebrow">OWNER CONTROL</p><h2>Report Format</h2><p class="muted">Change the form directly from the website. Your changes are saved in this browser without editing the code.</p><form id="rs" class="form"><label class="full">Report title<input id="rct" required value="${esc(db.reportConfig.title)}"></label><label class="full">Description<textarea id="rcd">${esc(db.reportConfig.description||'')}</textarea></label><div class="full"><div class="section-head"><h3>Fields</h3><button type="button" class="small accent" onclick="addReportField()">+ Add Field</button></div><div id="reportFieldsEditor" class="format-editor">${reportFieldsEditor()}</div></div><div class="actions"><button class="primary">Save Report Format</button></div></form>`);
  document.getElementById('rs').onsubmit=e=>{e.preventDefault();const fields=[...document.querySelectorAll('.format-row')].map(row=>({id:row.dataset.id,label:row.querySelector('.field-label').value.trim(),type:row.querySelector('.field-type').value,required:row.querySelector('.field-required').checked,options:(row.querySelector('.field-options')?.value||'').split(',').map(x=>x.trim()).filter(Boolean)})).filter(f=>f.label);if(!fields.length)return error('ADD A FIELD','A report must contain at least one field.');db.reportConfig={title:rct.value.trim(),description:rcd.value.trim(),fields};save();close();render()};
}
function reportFieldsEditor(){return db.reportConfig.fields.map(f=>`<div class="format-row" data-id="${esc(f.id)}"><input class="field-label" value="${esc(f.label)}" placeholder="Field name"><select class="field-type" onchange="toggleFieldOptions(this)"><option value="text" ${f.type==='text'?'selected':''}>Text</option><option value="textarea" ${f.type==='textarea'?'selected':''}>Long text</option><option value="date" ${f.type==='date'?'selected':''}>Date</option><option value="number" ${f.type==='number'?'selected':''}>Number</option><option value="select" ${f.type==='select'?'selected':''}>Choice</option></select><label class="check"><input class="field-required" type="checkbox" ${f.required?'checked':''}> Required</label><input class="field-options" placeholder="Choices: A, B, C" value="${esc((f.options||[]).join(', '))}" style="display:${f.type==='select'?'block':'none'}"><button type="button" class="small danger" onclick="this.closest('.format-row').remove()">Remove</button></div>`).join('')}
function addReportField(){const id='field_'+Date.now();document.getElementById('reportFieldsEditor').insertAdjacentHTML('beforeend',`<div class="format-row" data-id="${id}"><input class="field-label" placeholder="Field name"><select class="field-type" onchange="toggleFieldOptions(this)"><option value="text">Text</option><option value="textarea">Long text</option><option value="date">Date</option><option value="number">Number</option><option value="select">Choice</option></select><label class="check"><input class="field-required" type="checkbox"> Required</label><input class="field-options" placeholder="Choices: A, B, C" value=""><button type="button" class="small danger" onclick="this.closest('.format-row').remove()">Remove</button></div>`)}
function toggleFieldOptions(sel){const row=sel.closest('.format-row');row.querySelector('.field-options').style.display=sel.value==='select'?'block':'none'}

function complaint(){show(`<p class="eyebrow">PRIVATE FEEDBACK</p><h2>Lodge Complaint</h2><form id="cf" class="form"><label class="full">Subject<input id="ct" required></label><label class="full">Complaint<textarea id="cb" required></textarea></label><label class="full">Attach screenshot/file<input id="cfiles" type="file" multiple accept="image/*,.pdf,.doc,.docx"></label><div class="actions"><button class="primary">Submit Complaint</button></div></form>`);document.getElementById('cf').onsubmit=e=>{e.preventDefault();db.complaints.push({id:Date.now(),memberId:current.id,title:ct.value.trim(),body:cb.value.trim(),time:new Date().toISOString(),files:[...cfiles.files].map(f=>({name:f.name,type:f.type,size:f.size})),response:'',respondedBy:''});save();close();show('<p class="eyebrow">SUBMITTED</p><h2>Complaint sent.</h2><p class="muted">Squad leadership can now review it.</p>')}}
function respond(id){if(!isLeader())return;const c=db.complaints.find(x=>x.id===id);show(`<p class="eyebrow">LEADERSHIP</p><h2>Respond to Complaint</h2><form id="res"><textarea id="txt" required>${esc(c.response||'')}</textarea><button class="primary" style="margin-top:10px">Save Response</button></form>`);document.getElementById('res').onsubmit=e=>{e.preventDefault();c.response=txt.value.trim();c.respondedBy=current.name;save();close();render()}}

function eventForm(id){
  if(!isLeader())return error('LEADERSHIP ONLY','Only squad leadership can manage events.');
  const e=id?db.events.find(x=>x.id===id):{id:Date.now(),title:'',date:'',time:'',rules:'',body:''};
  show(`<p class="eyebrow">SQUAD EVENTS</p><h2>${id?'Edit Event':'Add Event'}</h2><form id="ef" class="form"><label class="full">Title<input id="et" required value="${esc(e.title)}"></label><label>Date<input id="ed" type="date" required value="${esc(e.date)}"></label><label>Start Time<input id="eti" type="time" value="${esc(e.time)}"></label><label class="full">Rules<textarea id="er" required placeholder="Enter the rules members need to follow.">${esc(e.rules)}</textarea></label><label class="full">Details <span class="muted">(optional)</span><textarea id="eb" placeholder="Short description, venue, prize, or other important information.">${esc(e.body)}</textarea></label><div class="actions"><button class="primary">${id?'Save Event':'Add Event'}</button></div></form>`);
  document.getElementById('ef').onsubmit=x=>{x.preventDefault();Object.assign(e,{title:et.value.trim(),date:ed.value,time:eti.value,rules:er.value.trim(),body:eb.value.trim()});if(!id)db.events.push(e);save();close();render()};
}
function removeEvent(id){if(!isLeader())return;if(confirm('Delete this event?')){db.events=db.events.filter(e=>e.id!==id);save();render()}}

/* ================= V5.8 STANDALONE TOURNAMENT CENTER ================= */
function ensureTournamentSchema(){
  // Keep built-in demo tournaments compatible with automatic team matchmaking.
  communityDb.tournaments=(communityDb.tournaments||[]).map(t=>{
    if(t.id==='T2' && t.format==='5v5' && Number(t.slots)===8 && !(t.matches||[]).length && !(communityDb.registrations||[]).some(r=>r.tournamentId==='T2')) t.slots=10;
    return t;
  });
  communityDb.tournaments=(communityDb.tournaments||[]).map(t=>{
    const completed=!!t.completed || String(t.status||'').toLowerCase()==='completed';
    return {...t,registrationOpen:t.registrationOpen!==false,matches:Array.isArray(t.matches)?t.matches:[],completed,champion:t.champion||'',runnerUp:t.runnerUp||'',completedAt:t.completedAt||null,cancelledAt:t.cancelledAt||null};
  });
  // Older saved tournaments that were already completed are migrated into the history state.
  communityDb.tournaments.forEach(t=>{if(t.completed){t.status='Completed';t.registrationOpen=false;if(!t.completedAt)t.completedAt=t.updatedAt||new Date().toISOString();}});
  communityDb.registrations=communityDb.registrations||[];
  communityDb.squadTournamentApprovals=Array.isArray(communityDb.squadTournamentApprovals)?communityDb.squadTournamentApprovals:[];
  communityDb.hallOfFame=communityDb.hallOfFame||[];
  communityDb.points=communityDb.points||{};
  enforceTournamentManagerEligibility();
  communityDb.tournaments.forEach(t=>{ const slots=Number(t.slots||0); const regs=communityDb.registrations.filter(r=>r.tournamentId===t.id); if(slots>0 && regs.length>=slots && t.registrationOpen!==false && !t.bracketReady) autoMatchmakeIfReady(t); });
  saveCommunity();
}
ensureTournamentSchema();
ensureCommunitySeason();
let tournamentView='overview';
let standingsView='tournament';
let pendingTournamentId=null;

function hideAllMain(){
  ['public','communityApp','app'].forEach(id=>document.getElementById(id)?.classList.add('hidden'));
  document.getElementById('tournamentPage')?.classList.remove('hidden');
  document.querySelector('footer')?.classList.add('hidden');
}
function openTournamentPage(){
  ensureTournamentSchema(); hideAllMain(); tournamentView='overview'; renderTournamentPage(); window.scrollTo(0,0);
}
function closeTournamentPage(){
  document.getElementById('tournamentPage')?.classList.add('hidden');
  if(current){document.getElementById('app').classList.remove('hidden');document.querySelector('footer').classList.add('hidden');window.scrollTo(0,0);render();return;}
  document.getElementById('public').classList.remove('hidden');document.querySelector('footer').classList.remove('hidden');enterCommunity();
}
function tourSetView(v){tournamentView=v;renderTournamentPage()}
function toggleTournamentMoreMenu(){const m=document.getElementById('tourMoreMenu');const tabs=m?.closest('.tour-tabs-compact');if(!m||!tabs)return;const open=!m.classList.contains('open');m.classList.toggle('open',open);tabs.classList.toggle('more-open',open);m.setAttribute('aria-hidden',String(!open));}
function tourButton(label,view,active=false){return `<button class="tour-tab ${active?'active':''}" onclick="tourSetView('${view}')">${label}</button>`}
function renderTournamentPage(){
  purgeExpiredCancelledTournaments();
  ensureTournamentSchema();
  const owner=tournamentAdminAccess();
  const open=communityDb.tournaments.filter(t=>isTournamentVisibleInAvailable(t)&&t.registrationOpen!==false);
  const regs=communityCurrent?communityDb.registrations.filter(r=>r.accountId===communityCurrent.id):[];
  const allRegs=communityDb.registrations;
  let body='';
  if(tournamentView==='overview') body=tourOverview(open,regs);
  if(tournamentView==='my') body=tourMyTournaments(regs);
  if(tournamentView==='matches') body=tourMatchCenter();
  if(tournamentView==='standings') body=standingsView==='community'?communityStandingsPanel():tournamentLeaderboard();
  if(tournamentView==='bracket') body=tourBracket();
  if(tournamentView==='workflow') body=tourWorkflow();
  if(tournamentView==='admin') body=owner?tourAdmin():tourAdminDenied();
  if(tournamentView==='management') body=owner?tourManagement():tourManagementDenied();
  if(tournamentView==='stApproval') body=tournamentAdminAccess()?stApprovalView():tourManagerDeniedForST();
  const moreActive=['standings','workflow','management','admin'].includes(tournamentView);
  const moreItems=`<div id="tourMoreMenu" class="tour-more-menu" aria-hidden="true">
    <button class="tour-more-item ${tournamentView==='standings'?'active':''}" onclick="tourSetView('standings')"><span>📊</span><b>Standings</b></button>
    <button class="tour-more-item ${tournamentView==='workflow'?'active':''}" onclick="tourSetView('workflow')"><span>❔</span><b>How It Works</b></button>
    ${owner?`<button class="tour-more-item ${tournamentView==='management'?'active':''}" onclick="tourSetView('management')"><span>⚙</span><b>Management</b></button>`:''}
    ${owner?`<button class="tour-more-item ${tournamentView==='admin'?'active':''}" onclick="tourSetView('admin')"><span>🛠</span><b>Tournament Admin</b></button>`:''}
  </div>`;
  document.getElementById('tournamentPage').innerHTML=`<div class="tournament-shell"><div class="tour-back"><button class="ghost" onclick="closeTournamentPage()">← Back</button></div><div class="tour-page-head"><div><span class="eyebrow">DARK SYSTEM • MLBB</span><h1>Tournament <em>Center.</em></h1><p class="muted">Register once, compete, submit proof, verify results and let the system handle the bracket and records.</p></div><div class="tour-actions"><button class="small notification-tool" onclick="toggleNotificationBar()">🔔 Notifications <span class="notification-count">${(communityDb.notifications||[]).filter(n=>!n.read&&(!n.audienceId||(communityCurrent&&String(n.audienceId)===String(communityCurrent.id)))).length}</span></button><button class="small accent" onclick="communityAuthForTournament()">${communityCurrent?'Community Dashboard':'Community Login'}</button></div></div><div class="tour-tabs tour-tabs-compact ${owner?'':'has-no-owner'}">${tourButton('Overview','overview',tournamentView==='overview')}${tourButton('My Tournaments','my',tournamentView==='my')}${tourButton('Match Center','matches',tournamentView==='matches')}${tourButton('Brackets','bracket',tournamentView==='bracket')}${tournamentAdminAccess()?tourButton('ST Approval','stApproval',tournamentView==='stApproval'):''}<div class="tour-more-wrap"><button class="tour-tab tour-more-toggle ${moreActive?'active':''}" onclick="toggleTournamentMoreMenu()">More <span>⌄</span></button>${moreItems}</div></div>${body}<div class="tour-page-footer">Semi-automatic verification: players submit results and proof; opponents can confirm or dispute; Owner approval resolves disputes and finalizes records.</div></div>`;
  bindTournamentAdmin();
}
function bindTournamentAdmin(){
  const f=document.getElementById('createTourForm');
  if(!f)return;
  f.onsubmit=async e=>{
    e.preventDefault();
    if(!tournamentAdminAccess()) return error('ACCESS DENIED','You do not have Tournament Manager permission.');
    const format=ntFormat.value;
    const slots=Number(ntSlots.value||0);
    const groupSize=format==='1v1'?1:(format==='2v2'?2:5);
    const minSlots=groupSize*2;
    if(slots<minSlots) return error('INVALID SLOT COUNT',`This ${format} tournament needs at least ${minSlots} player slots so automatic matchmaking can create two sides.`);
    if(slots%groupSize!==0) return error('INVALID SLOT COUNT',`For ${format}, total slots must be a multiple of ${groupSize}.`);
    if(format==='1v1' && slots%2!==0) return error('INVALID SLOT COUNT','A 1v1 tournament needs an even number of player slots.');
    const t={id:'T'+Date.now(),title:ntTitle.value.trim(),game:'Mobile Legends: Bang Bang',format,date:ntDate.value,time:ntTime.value,registrationDeadline:ntDeadline.value,slots,status:'Open',registrationOpen:true,reward:ntReward.value.trim()||'Tournament Rewards',rules:ntRules.value.trim(),description:ntDesc.value.trim(),matches:[],completed:false,champion:'',runnerUp:'',bracketReady:false,createdAt:new Date().toISOString()};
    communityDb.tournaments.push(t);
    addCommunityNotification('added','New tournament added',`${t.title} is now open for registration.`);
    saveCommunity();
    f.reset();
    ntSlots.value=String(format==='1v1'?32:format==='2v2'?8:10);
    tourSetView('admin');
  };
}
function communityStandingsPanel(){
  ensureCommunitySeason();
  const rows=communityLeaderboardRows().slice(0,20), season=getCurrentCommunitySeason();
  return `<section class="tour-admin-card"><div class="section-intro"><div><span class="eyebrow">COMMUNITY STANDINGS</span><h2>Community <em>Leaderboard.</em></h2><p class="muted">Season ${esc(season.season)} • resets with the MLBB season calendar. Win = 100 points, Loss = 50 points, qualifying event participation = 50 points.</p></div><span class="tour-chip">${esc(season.season)}</span></div><div class="leaderboard-preview" style="margin-top:18px"><div class="leader-row head"><span>#</span><span>PLAYER</span><span>RECORD</span><span>POINTS</span></div>${rows.map((x,i)=>`<div class="leader-row"><b>${String(i+1).padStart(2,'0')}</b><strong>${esc(x.a.ign)}</strong><span>${x.wins}W • ${x.losses}L • ${x.events} events</span><b>${x.p}</b></div>`).join('')||'<div class="leader-row"><b>01</b><strong>No scores yet</strong><span>Participate to appear here</span><b>0</b></div>'}</div><div class="actions" style="margin-top:18px"><button class="small accent" onclick="tourSetStandings('tournament')">View Tournament Leaderboard</button></div></section>`;
}
function tourSetStandings(v){standingsView=v; tournamentView='standings'; renderTournamentPage();}
function tournamentLeaderboard(){const active=communityDb.tournaments.filter(t=>!t.completed&&String(t.status||'').toLowerCase()!=='cancelled');if(!active.length)return '<section class="tour-empty"><b>No ongoing tournaments.</b><p>The Tournament Leaderboard will appear when a tournament is active.</p></section>';const t=active[0];const ids=new Set(communityDb.registrations.filter(r=>String(r.tournamentId)===String(t.id)).map(r=>String(r.accountId)));const rows=[...ids].map(id=>{let wins=0,losses=0;(t.matches||[]).forEach(m=>{if(String(m.winner)===id)wins++;else if((String(m.player1)===id||String(m.player2)===id)&&m.winner)losses++;});return{a:communityDb.accounts.find(a=>String(a.id)===id),wins,losses,score:wins*100+losses*50};}).filter(x=>x.a).sort((a,b)=>b.wins-a.wins||b.score-a.score);return `<section class="tour-admin-card"><div class="section-intro"><div><span class="eyebrow">ONGOING TOURNAMENT</span><h2>${esc(t.title)} <em>Leaderboard.</em></h2><p class="muted">This board is separate from the Community Leaderboard. It only measures performance inside this ongoing tournament.</p></div><span class="tour-chip">${esc(t.status||'Open')}</span></div><div class="leaderboard-preview" style="margin-top:18px"><div class="leader-row head"><span>#</span><span>PLAYER</span><span>RECORD</span><span>SCORE</span></div>${rows.map((x,i)=>`<div class="leader-row"><b>${String(i+1).padStart(2,'0')}</b><strong>${esc(x.a.ign)}</strong><span>${x.wins}W • ${x.losses}L</span><b>${x.score}</b></div>`).join('')||'<div class="leader-row"><strong>No results yet</strong><span>Verified matches will populate this board.</span><b>—</b></div>'}</div><div class="actions" style="margin-top:18px"><button class="small accent" onclick="tourSetStandings('community')">View Community Leaderboard</button></div></section>`;}
function tourWorkflow(){return `<section class="workflow-hero"><span class="eyebrow">SEMI-AUTOMATIC MLBB TOURNAMENT SYSTEM</span><h2>Play the match. <em>Let Dark System handle the rest.</em></h2><p class="muted">The website manages registration, brackets, result verification, advancement, tournament records and leaderboard updates while the Owner remains the final authority.</p></section><div class="workflow-grid"><article><b>01</b><h3>Register</h3><p>Use one Community profile to enter any open MLBB tournament.</p></article><article><b>02</b><h3>Generate Bracket</h3><p>The Owner closes registration and generates the tournament bracket automatically.</p></article><article><b>03</b><h3>Play MLBB</h3><p>Players play their scheduled match inside Mobile Legends: Bang Bang.</p></article><article><b>04</b><h3>Submit Result</h3><p>The player submits the winner, MLBB Match ID and screenshot/proof.</p></article><article><b>05</b><h3>Confirm or Dispute</h3><p>The opponent can confirm the result. A disagreement sends it to Owner review.</p></article><article><b>06</b><h3>Automatic Updates</h3><p>Once verified, the bracket advances, points are awarded and the match is recorded.</p></article><article><b>07</b><h3>Champion</h3><p>When the final is verified, the tournament is completed and the champion is recorded.</p></article><article><b>08</b><h3>Hall of Fame</h3><p>The completed championship can be added permanently to Dark System history.</p></article></div><section class="workflow-note"><h3>Verification rule</h3><p><b>Player submits → Opponent confirms → System processes.</b> If disputed, the Squad Owner reviews the evidence and decides.</p></section>`}
function isTournamentVisibleInAvailable(t){return t.status==='Open' || (String(t.status||'').toLowerCase()==='cancelled' && cancelledRemainingMs(t)>0)}
function tourOverview(open,regs){
  const completed=communityDb.tournaments.filter(t=>t.completed).length;
  return `<div class="tour-stat-row"><div class="tour-stat-card"><small>OPEN TOURNAMENTS</small><b>${open.length}</b></div><div class="tour-stat-card"><small>MY REGISTRATIONS</small><b>${regs.length}</b></div><div class="tour-stat-card"><small>COMPLETED</small><b>${completed}</b></div><div class="tour-stat-card"><small>PROOF-BASED</small><b>100%</b></div></div><div class="tour-login-note">${communityCurrent?`Logged in as <b>${esc(communityCurrent.ign)}</b>. Your saved profile will be reused for every registration.`:'You can browse freely. To register for a tournament, create or log in to your Community account.'}</div><div class="section-intro"><div><span class="eyebrow">OPEN NOW</span><h2>Available <em>Tournaments.</em></h2></div></div><div class="tour-grid-large">${open.map(t=>tourCard(t,regs)).join('')||'<div class="tour-empty"><b>No tournaments are open right now.</b><p>The Owner will publish the next MLBB competition here.</p></div>'}</div>`;
}
function tourCard(t,regs){
  const registered=regs.some(r=>r.tournamentId===t.id);
  const cancelled=String(t.status||'').toLowerCase()==='cancelled';
  return `<article class="tour-feature-card ${cancelled?'cancelled-tour-card':''}"><span class="tour-chip">${esc(cancelled?'CANCELLED':(t.format||'MLBB'))}</span><h3>${esc(t.title)}</h3><p class="muted">${esc(t.description||'Mobile Legends: Bang Bang tournament.')}</p><div class="event-public-meta"><span>📅 ${esc(t.date||'TBA')}</span><span>⏰ ${esc(t.time||'TBA')}</span><span>👥 ${t.format==='Squad vs Squad'?esc(t.squadSlots||0)+' squads':esc(t.slots||'Open')+' slots'}</span>${t.format==='Squad vs Squad'?`<span>👤 ${esc(t.membersPerSquad||7)} / squad</span>`:''}<span>🏆 ${esc(t.reward||'Rewards')}</span></div><p><b>Rules:</b> ${esc(t.rules||'Standard Dark System tournament rules apply.')}</p><div class="tour-actions">${cancelled?`<span class="pending-badge">Reinstatement window: ${cancelledRemainingText(t)}</span>`:(registered?'<button type="button" class="small registered-state" aria-label="Already registered">✓ Registered</button>':`<button type="button" class="small accent" onclick="registerFromTournament('${t.id}')">Register</button>`)}<button type="button" class="small" onclick="tourDetails('${t.id}')">Details</button></div></article>`;
}
function tourDetails(id){const t=communityDb.tournaments.find(x=>x.id===id);if(!t)return;show(`<div class="login-wrap"><span class="eyebrow">TOURNAMENT DETAILS</span><h2>${esc(t.title)}</h2><p class="muted">${esc(t.description||'Mobile Legends: Bang Bang')}</p><div class="profile-data"><div><small>FORMAT</small><b>${esc(t.format||'MLBB')}</b></div><div><small>DATE</small><b>${esc(t.date||'TBA')}</b></div><div><small>START</small><b>${esc(t.time||'TBA')}</b></div><div><small>REGISTRATION</small><b>${esc(t.registrationDeadline||'Open until closed')}</b></div><div><small>PRIZE</small><b>${esc(t.reward||'TBA')}</b></div><div><small>${t.format==='Squad vs Squad'?'SQUADS':'SLOTS'}</small><b>${t.format==='Squad vs Squad'?esc(t.squadSlots||0)+' squads • '+esc(t.membersPerSquad||7)+'/squad':esc(t.slots||'Open')}</b></div></div><p><b>Rules</b><br>${esc(t.rules||'Standard Dark System tournament rules apply.')}</p><div class="actions">${communityCurrent&&communityDb.registrations.some(r=>r.accountId===communityCurrent.id&&r.tournamentId===t.id)?'<button type="button" class="primary registered-state" onclick="close();renderTournamentPage()">✓ Registered</button>':`<button type="button" class="primary" onclick="close();registerFromTournament('${t.id}')">Register</button>`}<button type="button" class="ghost" onclick="close()">Close</button></div></div>`)}
function communityAuthForTournament(){
  if(current) return error('SQUAD PORTAL ACTIVE','You are logged in to the Squad Portal. Please log out before logging in to Community.');
  if(communityCurrent) return error('ALREADY LOGGED IN','You are already logged in to Community. Use the Community Dashboard or log out first.');
  communityAuth();
}
function registerFromTournament(id){
  const t=communityDb.tournaments.find(x=>String(x.id)===String(id));
  if(!t||String(t.status||'').toLowerCase()!=='open'||t.registrationOpen===false)return error('REGISTRATION CLOSED','This tournament is not open for registration.');
  if(!communityCurrent){pendingTournamentId=id;communityAuth();return;}
  if(communityDb.registrations.some(r=>String(r.accountId)===String(communityCurrent.id)&&String(r.tournamentId)===String(id)))return error('ALREADY REGISTERED','You are already registered for this tournament.');
  if(t.format==='Squad vs Squad') return squadTournamentRegistration(t);
  const count=communityDb.registrations.filter(r=>String(r.tournamentId)===String(id)).length;
  if(Number(t.slots)&&count>=Number(t.slots))return error('TOURNAMENT FULL','All available registration slots have been filled.');
  communityDb.registrations.push({id:Date.now(),accountId:communityCurrent.id,tournamentId:id,ign:communityCurrent.ign,gameId:communityCurrent.gameId,serverId:communityCurrent.serverId,status:'Registered',registeredAt:new Date().toISOString()});saveCommunity();
  show(`<div class="setup-lock"><div class="setup-icon">✓</div><span class="eyebrow">REGISTRATION COMPLETE</span><h2>${esc(t.title)}</h2><p class="muted">${esc(communityCurrent.ign)}, your saved Community profile has been registered. You can follow your matches from Match Center.</p><div class="actions"><button class="primary" onclick="close();renderTournamentPage()">Done</button></div></div>`);
}
function generateTournamentCode(prefix='DS-ST'){return `${prefix}-${Math.random().toString(36).slice(2,7).toUpperCase()}-${Math.random().toString(36).slice(2,5).toUpperCase()}`;}
function copyAccessCode(code,button){const value=String(code||'').trim();if(!value)return;const done=()=>{if(button){const old=button.textContent;button.textContent='✓ Copied';button.disabled=true;setTimeout(()=>{button.textContent=old;button.disabled=false;},1400);}};if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(value).then(done).catch(()=>fallbackCopy(value,done));}else{fallbackCopy(value,done);}}
function fallbackCopy(value,done){const ta=document.createElement('textarea');ta.value=value;ta.setAttribute('readonly','');ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();try{document.execCommand('copy');done();}finally{ta.remove();}}
function squadTournamentRegistration(t){
  const member=db.members.find(m=>String(m.communityAccountId)===String(communityCurrent.id)) || db.members.find(m=>String(m.id)===String(communityCurrent.squadMemberId));
  const role=member?.role||communityCurrent.role||'Squad Member';
  if(role==='Squad Owner')return error('SQUAD OWNER REGISTRATION','A Squad Leader must submit the squad registration. You can participate as a member after the squad is approved.');
  if(role==='Squad Leader'){
    if(!t.squadRegistrationOpen)return error('SQUAD REGISTRATION CLOSED','All squad slots have been filled or squad registration has closed.');
    show(`<div class="login-wrap squad-st-registration"><span class="eyebrow">SQUAD TOURNAMENT REGISTRATION</span><h2>Register Your Squad.</h2><p class="muted">Your Community profile is already recognized. Enter only the squad details and invitation code.</p><form id="stLeaderForm" class="form"><label>Community Profile<input value="${esc(communityCurrent.ign)} • ${esc(communityCurrent.gameId)} / ${esc(communityCurrent.serverId)}" disabled></label><label>In-Game Squad Name<input id="stSquadName" required placeholder="Exact MLBB squad name"></label><label>Squad ID<input id="stSquadId" required placeholder="Exact MLBB squad ID"></label><label>Squad Role<input value="Squad Leader" disabled></label><label>Tournament Access Code<input id="stLeaderCode" required placeholder="Enter the invitation code"></label><div class="notice"><b>Identity rule</b><br><span>Squad name and Squad ID must exactly match Mobile Legends: Bang Bang.</span></div><div class="actions"><button class="primary">Submit for Approval</button><button type="button" class="ghost" onclick="close()">Cancel</button></div></form></div>`);
    document.getElementById('stLeaderForm').onsubmit=e=>{e.preventDefault();submitSTLeaderRegistration(t.id,stSquadName.value.trim(),stSquadId.value.trim(),stLeaderCode.value.trim(),communityCurrent,member);}; return;
  }
  const squads=(communityDb.squadTournamentApprovals||[]).filter(a=>String(a.tournamentId)===String(t.id)&&a.status==='Approved');
  if(!squads.length)return error('SQUADS NOT OPEN','No approved squads are available for member registration yet.');
  show(`<div class="login-wrap squad-st-registration"><span class="eyebrow">SQUAD TOURNAMENT REGISTRATION</span><h2>Join Your Squad.</h2><p class="muted">Your Community profile is already recognized. Enter the unique code sent to you by your Squad Leader.</p><form id="stMemberForm" class="form"><label>Community Profile<input value="${esc(communityCurrent.ign)} • ${esc(communityCurrent.gameId)} / ${esc(communityCurrent.serverId)}" disabled></label><label>Squad Member Access Code<input id="stMemberCode" required placeholder="Enter your squad code"></label><div class="notice"><b>5v5 squad structure</b><br><span>Each squad can register up to ${esc(t.membersPerSquad||7)} members: 5 starters and the remaining members are substitutes.</span></div><div class="actions"><button class="primary">Join Squad</button><button type="button" class="ghost" onclick="close()">Cancel</button></div></form></div>`);
  document.getElementById('stMemberForm').onsubmit=e=>{e.preventDefault();submitSTMemberRegistration(t.id,stMemberCode.value.trim(),communityCurrent);};
}
function submitSTLeaderRegistration(tid,squadName,squadId,code,account,member){
  const t=communityDb.tournaments.find(x=>String(x.id)===String(tid));
  if(!t||t.format!=='Squad vs Squad')return error('INVALID TOURNAMENT','This is not a Squad-vs-Squad tournament.');
  if(!t.squadRegistrationOpen)return error('SQUAD REGISTRATION CLOSED','Squad registration is closed.');
  if(code!==t.leaderAccessCode)return error('INVALID ACCESS CODE','The tournament invitation code is invalid.');
  if((communityDb.squadTournamentApprovals||[]).some(a=>String(a.tournamentId)===String(tid)&&a.status==='Pending'&&String(a.leaderAccountId)===String(account.id)))return error('ALREADY SUBMITTED','Your squad registration is already awaiting approval.');
  if((communityDb.squadTournamentApprovals||[]).some(a=>String(a.tournamentId)===String(tid)&&a.status==='Approved'&&String(a.leaderAccountId)===String(account.id)))return error('ALREADY APPROVED','You already have an approved squad registration for this tournament.');
  const approvedCount=(communityDb.squadTournamentApprovals||[]).filter(a=>String(a.tournamentId)===String(tid)&&a.status==='Approved').length;
  if(approvedCount>=Number(t.squadSlots||0))return error('SQUAD SLOTS FULL','All squad slots have already been approved.');
  const a={id:'STA'+Date.now()+Math.random().toString(36).slice(2,6),tournamentId:tid,tournamentTitle:t.title,squadName,squadId,leaderAccountId:account.id,leaderMemberId:member?.id||null,leaderIgn:account.ign,leaderGameId:account.gameId,leaderServerId:account.serverId,role:'Squad Leader',status:'Pending',createdAt:new Date().toISOString(),maxSquads:Number(t.squadSlots||0),membersPerSquad:Number(t.membersPerSquad||7)};
  communityDb.squadTournamentApprovals.push(a);addCommunityNotification('squad_registration','Squad Tournament Registration Submitted',`Your squad registration for ${t.title} has been submitted and is awaiting Tournament Admin approval.`,account.id);saveCommunity();close();renderTournamentPage();
}
function submitSTMemberRegistration(tid,code,account){
  const t=communityDb.tournaments.find(x=>String(x.id)===String(tid));
  if(!t||t.format!=='Squad vs Squad')return error('INVALID TOURNAMENT','This is not a Squad-vs-Squad tournament.');
  const approval=(communityDb.squadTournamentApprovals||[]).find(a=>String(a.tournamentId)===String(tid)&&a.status==='Approved'&&String(a.memberAccessCode||'')===String(code));
  if(!approval)return error('INVALID SQUAD CODE','That code is invalid, or the squad has not been approved.');
  if(communityDb.registrations.some(r=>String(r.tournamentId)===String(tid)&&String(r.accountId)===String(account.id)))return error('ALREADY REGISTERED','You are already registered for this tournament.');
  const squadCount=communityDb.registrations.filter(r=>String(r.tournamentId)===String(tid)&&String(r.squadApprovalId)===String(approval.id)).length;
  if(squadCount>=Number(t.membersPerSquad||approval.membersPerSquad||7))return error('SQUAD FULL','This squad has reached its maximum registered members.');
  communityDb.registrations.push({id:'R'+Date.now()+Math.random().toString(36).slice(2,6),accountId:account.id,tournamentId:tid,ign:account.ign,gameId:account.gameId,serverId:account.serverId,status:'Registered',registeredAt:new Date().toISOString(),squadApprovalId:approval.id,squadName:approval.squadName,squadId:approval.squadId,squadRole:account.role||'Squad Member',isSubstitute:squadCount>=5});
  saveCommunity();close();renderTournamentPage();show(`<div class="setup-lock"><div class="setup-icon">✓</div><span class="eyebrow">SQUAD REGISTRATION COMPLETE</span><h2>${esc(t.title)}</h2><p class="muted">${esc(account.ign)} has been registered to <b>${esc(approval.squadName)}</b>. ${squadCount>=5?'You are currently recorded as a substitute.':'You are within the first five registered players.'}</p><div class="actions"><button class="primary" onclick="close();renderTournamentPage()">Done</button></div></div>`);
}
function tourMyTournaments(regs){
  return `<section class="panel"><div class="section-head"><div><span class="eyebrow">YOUR HISTORY</span><h2>My Tournaments</h2></div></div>${communityCurrent?regs.map(r=>{const t=communityDb.tournaments.find(x=>x.id===r.tournamentId);return t?`<div class="tour-list-row"><div><b>${esc(t.title)}</b><div class="meta">${esc(t.format||'MLBB')} • ${esc(t.date||'TBA')}</div></div><span class="tour-chip">${esc(r.status||'Registered')}</span></div>`:''}).join('')||'<div class="tour-empty">You have not registered for a tournament yet.</div>':'<div class="tour-login-note">Log in to see your tournament registrations.</div>'}</section>`;
}
function tourBracket(){
  purgeExpiredCancelledTournaments();
  const generated=communityDb.tournaments.filter(t=>Array.isArray(t.matches)&&t.matches.length)
    .slice().sort((a,b)=>new Date(b.completedAt||b.date||b.createdAt||0)-new Date(a.completedAt||a.date||a.createdAt||0));
  if(!generated.length)return '<div class="tour-empty"><b>No brackets generated yet.</b><p>The Owner generates a bracket after registration closes.</p></div>';
  const recent=generated.slice(0,5), older=generated.slice(5);
  const renderCard=t=>{
    const max=Math.max(...t.matches.map(m=>m.round||1));let rounds='';
    for(let r=1;r<=max;r++){
      const ms=t.matches.filter(m=>m.round===r);
      rounds+=`<div class="bracket-round"><h4>ROUND ${r}</h4>${ms.map(m=>{const a=communityDb.accounts.find(x=>String(x.id)===String(m.player1)),b=communityDb.accounts.find(x=>String(x.id)===String(m.player2));return `<div class="bracket-match"><small>Match #${esc(m.number)}</small><div class="${m.winner===m.player1?'winner':''}"><span>${esc(a?.ign||'BYE')}</span><b>${m.winner===m.player1?'✓':''}</b></div><div class="${m.winner===m.player2?'winner':''}"><span>${esc(b?.ign||'BYE')}</span><b>${m.winner===m.player2?'✓':''}</b></div>${m.submission?`<small>${esc(m.submission.status)}</small>`:''}</div>`}).join('')}</div>`;
    }
    const regs=communityDb.registrations.filter(r=>String(r.tournamentId)===String(t.id)).length;
    const champ=communityDb.accounts.find(a=>String(a.id)===String(t.champion));
    const runner=communityDb.accounts.find(a=>String(a.id)===String(t.runnerUp));
    const status=String(t.status||'Open');
    const when=t.completedAt?`Completed ${fmt(t.completedAt)}`:`Tournament date ${dateOnly(t.date)||'TBA'}${t.time?' • '+t.time:''}`;
    return `<section class="tour-admin-card bracket-history-card"><div class="section-head"><div><span class="eyebrow">${t.completed?'COMPLETED BRACKET':'LIVE BRACKET'}</span><h3>${esc(t.title)}</h3><p class="muted">${esc(when)}</p></div><span class="tour-chip">${esc(status)}</span></div><div class="bracket-identity"><span>🎮 ${esc(t.game||'Mobile Legends: Bang Bang')}</span><span>⚔ ${esc(t.format||'MLBB')}</span><span>👥 ${regs}/${esc(t.slots||'—')} registered</span><span>🏆 ${esc(t.reward||'Rewards')}</span></div>${champ?`<div class="bracket-result"><b>Champion:</b> ${esc(champ.ign)}${runner?` <span>• Runner-up: ${esc(runner.ign)}</span>`:''}</div>`:''}<div class="bracket"><div class="bracket-rounds-wrap">${rounds}</div></div></section>`;
  };
  return `<div class="bracket-history-head"><div><span class="eyebrow">LIVE + COMPLETED</span><h2>Tournament <em>Brackets.</em></h2><p class="muted">The five most recent brackets stay expanded. Older brackets remain here in a minimized state and can be opened whenever you need them.</p></div>${older.length?`<button class="small accent" type="button" onclick="toggleOlderBrackets()" id="olderBracketsBtn">Expand ${older.length} older bracket${older.length===1?'':'s'} ↑</button>`:''}</div><div class="tour-list bracket-history-list">${recent.map(renderCard).join('')}</div>${older.length?`<div id="olderBrackets" class="tour-list older-brackets minimized">${older.map(renderCard).join('')}</div>`:''}`;
}
function toggleOlderBrackets(){const box=document.getElementById('olderBrackets'),btn=document.getElementById('olderBracketsBtn');if(!box||!btn)return;const open=box.classList.toggle('minimized');btn.textContent=open?`Expand ${box.children.length} older bracket${box.children.length===1?'':'s'} ↑`:'Hide older brackets ↓';}

function tourMatchCenter(){
  const ids=communityCurrent?communityDb.registrations.filter(r=>r.accountId===communityCurrent.id).map(r=>r.tournamentId):[];
  const matches=[]; communityDb.tournaments.forEach(t=>(t.matches||[]).forEach(m=>{if(!communityCurrent||ids.includes(t.id))matches.push({t,m})}));
  return `<section><div class="section-intro"><div><span class="eyebrow">PLAY • PROVE • VERIFY</span><h2>Match <em>Center.</em></h2><p>Submit results after your MLBB match. Opponents can confirm or dispute before Owner review.</p></div></div>${matches.length?`<div class="tour-list">${matches.map(x=>matchCard(x.t,x.m)).join('')}</div>`:'<div class="tour-empty"><b>No matches yet.</b><p>Once the Owner generates a bracket for a tournament you registered for, your matches will appear here.</p></div>'}</section>`;
}
function matchCard(t,m){
  const me=communityCurrent?.id; const p1=communityDb.accounts.find(a=>a.id===m.player1);const p2=communityDb.accounts.find(a=>a.id===m.player2);const sub=m.submission;
  const canSubmit=me&&(me===m.player1||me===m.player2)&&!m.winner;
  const opponent=me===m.player1?m.player2:m.player1;
  return `<article class="match-card"><div class="section-head"><div><span class="eyebrow">${esc(t.title)}</span><h3>Match #${esc(m.number)}</h3></div>${m.winner?'<span class="verified-badge">VERIFIED</span>':sub?`<span class="pending-badge">${esc(sub.status||'AWAITING VERIFICATION').toUpperCase()}</span>`:'<span class="tour-chip">PENDING</span>'}</div><div class="bracket-match"><div class="${m.winner===m.player1?'winner':''}"><span>${esc(p1?.ign||'Player 1')}</span><b>${m.winner===m.player1?'W':''}</b></div><div class="${m.winner===m.player2?'winner':''}"><span>${esc(p2?.ign||'Player 2')}</span><b>${m.winner===m.player2?'W':''}</b></div></div>${sub?`<p class="muted">Result: <b>${esc(sub.submitterResult||'Win')}</b> • Winner: <b>${esc(communityDb.accounts.find(a=>a.id===sub.winner)?.ign||'Unknown')}</b> • MLBB Battle ID: <b>${esc(sub.battleId||sub.matchId||'Not provided')}</b> • Proof: <span class="proof-file">${esc(sub.proof||'Not provided')}</span></p>`:''}<div class="tour-actions">${canSubmit?`<button class="small accent" onclick="submitMatchResult('${t.id}','${m.id}')">Submit Result</button>`:''}${sub&&me===opponent&&sub.status==='Awaiting Confirmation'?`<button class="small accent" onclick="confirmMatch('${t.id}','${m.id}')">Confirm Result</button><button class="small danger" onclick="disputeMatch('${t.id}','${m.id}')">Dispute</button>`:''}</div></article>`;
}
function submitMatchResult(tid,mid){
  const t=communityDb.tournaments.find(x=>x.id===tid),m=t?.matches?.find(x=>String(x.id)===String(mid));if(!t||!m)return;
  const me=communityCurrent?.id;
  if(!me || (me!==m.player1 && me!==m.player2)) return error('ACCESS DENIED','Only a player in this match can submit the result.');
  if(m.winner || m.submission) return error('RESULT ALREADY SUBMITTED','This match already has a submitted or verified result.');
  const p1=communityDb.accounts.find(a=>a.id===m.player1),p2=communityDb.accounts.find(a=>a.id===m.player2);
  const opponent=me===m.player1?m.player2:m.player1;
  const meAccount=communityDb.accounts.find(a=>a.id===me);
  const opponentAccount=communityDb.accounts.find(a=>a.id===opponent);
  show(`<div class="login-wrap"><span class="eyebrow">MATCH RESULT</span><h2>Submit Match #${esc(m.number)}</h2><p class="muted">Select whether <b>${esc(meAccount?.ign||'you')}</b> won or lost. The other player will be asked to confirm.</p><form id="resultForm" class="form"><label>My Result<select id="rresult" required><option value="Win">🟢 Win</option><option value="Loss">🔴 Loss</option></select></label><p class="muted result-choice-note">Choose the result from your perspective. The system will automatically identify the winner/loser and tie it to this MLBB Battle ID.</p><label>MLBB Battle ID<input id="rmid" required inputmode="numeric" placeholder="e.g. 485944043449967111"></label><label class="full">Screenshot / proof<input id="rproof" type="file" accept="image/*"></label><div class="profile-data full"><div><small>YOU</small><b>${esc(meAccount?.ign||'Player')}</b></div><div><small>OPPONENT</small><b>${esc(opponentAccount?.ign||'Opponent')}</b></div></div><div class="actions"><button type="submit" class="primary">Submit Result</button><button type="button" class="ghost" id="cancelResultBtn">Cancel</button></div></form></div>`);
  const form=document.getElementById('resultForm');
  const cancel=document.getElementById('cancelResultBtn');
  if(cancel) cancel.addEventListener('click',()=>close());
  if(form) form.addEventListener('submit',e=>{
    e.preventDefault();
    const result=document.getElementById('rresult').value;
    const battleId=document.getElementById('rmid').value.trim();
    if(!battleId) return error('BATTLE ID REQUIRED','Enter the MLBB Battle ID shown on the completed match results screen.');
    const winner=result==='Win'?me:opponent;
    const payload={winner:Number(winner),submittedBy:communityCurrent.id,submitterResult:result,battleId,matchId:battleId,proof:document.getElementById('rproof').files?.[0]?.name||'Proof not attached',status:'Awaiting Confirmation',submittedAt:new Date().toISOString()};
    if(DARK_BACKEND){api('/api/tournaments/result',{method:'POST',body:JSON.stringify({tournamentId:String(tid),matchId:String(mid),result:payload})}).then(data=>{if(data.tournament){const i=communityDb.tournaments.findIndex(x=>String(x.id)===String(tid));if(i>=0)communityDb.tournaments[i]=data.tournament;}}).catch(err=>error('RESULT SUBMISSION FAILED',err.message));}
    else {m.submission=payload;saveCommunity();}
    close();
    renderTournamentPage();
    show(`<div class="setup-lock"><div class="setup-icon">✓</div><span class="eyebrow">RESULT SUBMITTED</span><h2>${esc(result)}</h2><p class="muted">You submitted <b>${esc(result)}</b> for ${esc(meAccount?.ign||'your account')}. The opponent must confirm the result before it is verified.</p><div class="profile-data"><div><small>MLBB BATTLE ID</small><b>${esc(battleId)}</b></div><div><small>OPPONENT</small><b>${esc(opponentAccount?.ign||'Opponent')}</b></div></div><div class="actions"><button type="button" class="primary" id="resultDoneBtn">Done</button></div></div>`);
    const done=document.getElementById('resultDoneBtn'); if(done) done.addEventListener('click',()=>close());
  });
}
async function confirmMatch(tid,mid){
  try{if(DARK_BACKEND){const r=await api('/api/tournaments/result-confirm',{method:'POST',body:JSON.stringify({tournamentId:String(tid),matchId:String(mid)})});if(r.tournament){const i=communityDb.tournaments.findIndex(x=>String(x.id)===String(tid));if(i>=0)communityDb.tournaments[i]=r.tournament;}}else{const t=communityDb.tournaments.find(x=>x.id===tid),m=t?.matches?.find(x=>String(x.id)===String(mid));if(!m?.submission)return;m.winner=m.submission.winner;m.submission.status='Confirmed';m.verifiedAt=new Date().toISOString();awardTournamentPoints(t,m);advanceMatch(t,m);saveCommunity();}renderTournamentPage();}catch(err){error('RESULT CONFIRMATION FAILED',err.message)}}
async function disputeMatch(tid,mid){
  try{if(DARK_BACKEND){const r=await api('/api/tournaments/result-dispute',{method:'POST',body:JSON.stringify({tournamentId:String(tid),matchId:String(mid)})});if(r.tournament){const i=communityDb.tournaments.findIndex(x=>String(x.id)===String(tid));if(i>=0)communityDb.tournaments[i]=r.tournament;}}else{const t=communityDb.tournaments.find(x=>x.id===tid),m=t?.matches?.find(x=>String(x.id)===String(mid));if(!m?.submission)return;m.submission.status='Disputed';saveCommunity();}show(`<div class="setup-lock"><div class="setup-icon">!</div><span class="eyebrow">DISPUTE OPENED</span><h2>Owner review required</h2><p class="muted">The result has been marked as disputed. The Squad Owner must review the proof before the bracket advances.</p><div class="actions"><button class="primary" onclick="close();renderTournamentPage()">Done</button></div></div>`);}catch(err){error('DISPUTE FAILED',err.message)}}
function awardTournamentPoints(t,m){if(m.pointsAwarded)return;communityDb.seasonPoints=communityDb.seasonPoints||{};const winner=String(m.winner),loser=String(m.player1)===winner?String(m.player2):String(m.player1);communityDb.seasonPoints[winner]=(communityDb.seasonPoints[winner]||0)+100;if(loser&&loser!=='undefined')communityDb.seasonPoints[loser]=(communityDb.seasonPoints[loser]||0)+50;m.pointsAwarded=true;saveCommunity();processCommunitySeason();}
function advanceMatch(t,m){
  if(!t.matches)return;
  const sameRound=t.matches.filter(x=>x.round===m.round&&x.id!==m.id);
  const next=t.matches.find(x=>x.round===m.round+1&&(!x.player1||!x.player2));
  if(next){if(!next.player1)next.player1=m.winner;else if(!next.player2)next.player2=m.winner;}
  const unfinished=t.matches.some(x=>!x.winner&&x.player1&&x.player2);
  if(!unfinished){
    const finalRound=Math.max(...t.matches.map(x=>x.round||1));
    const final=t.matches.filter(x=>x.round===finalRound).find(x=>x.winner);
    if(final?.winner){
      t.completed=true;
      t.status='Completed';
      t.registrationOpen=false;
      t.champion=final.winner;
      const loser=final.winner===final.player1?final.player2:final.player1;
      t.runnerUp=loser||'';
      t.completedAt=t.completedAt||new Date().toISOString();
      if(!communityDb.hallOfFame.some(h=>h.tournamentId===t.id)) communityDb.hallOfFame.push({id:Date.now(),tournamentId:t.id,title:t.title,champion:t.champion,runnerUp:t.runnerUp,date:t.date,completedAt:t.completedAt});
    }
  }
}
function tourAdmin(){
  const pending=[];communityDb.tournaments.forEach(t=>(t.matches||[]).forEach(m=>{if(m.submission&&['Awaiting Confirmation','Disputed'].includes(m.submission.status))pending.push({t,m})}));
  return `<div class="tour-stat-row"><div class="tour-stat-card"><small>TOURNAMENTS</small><b>${communityDb.tournaments.length}</b></div><div class="tour-stat-card"><small>REGISTRATIONS</small><b>${communityDb.registrations.length}</b></div><div class="tour-stat-card"><small>PENDING REVIEWS</small><b>${pending.length}</b></div><div class="tour-stat-card"><small>HALL OF FAME</small><b>${communityDb.hallOfFame.length}</b></div></div><div class="admin-grid"><section class="tour-admin-card"><span class="eyebrow">OWNER CONTROL</span><h3>Create Tournament</h3><form id="createTourForm" class="tour-form"><label>Title<input id="ntTitle" required placeholder="Dark System 1v1 Championship"></label><label>Format<select id="ntFormat"><option>1v1</option><option>5v5</option><option>2v2</option></select></label><label>Game<input value="Mobile Legends: Bang Bang" disabled></label><label>Date<input id="ntDate" type="date" required></label><label>Start Time<input id="ntTime" type="time" required></label><label>Registration Deadline<input id="ntDeadline" type="date"></label><label>Slots<input id="ntSlots" type="number" min="2" value="32" required></label><label>Prize / Reward<input id="ntReward" placeholder="₦10,000"></label><label class="full">Rules<textarea id="ntRules" required placeholder="Enter the tournament rules..."></textarea></label><label class="full">Description<textarea id="ntDesc" placeholder="Tournament description..."></textarea></label><div class="actions full"><button class="primary">Publish Tournament</button></div></form></section><section class="tour-admin-card"><span class="eyebrow">TOURNAMENTS</span><h3>Manage Existing</h3><div class="tour-list">${communityDb.tournaments.map(t=>`<div class="tour-list-row"><div><b>${esc(t.title)}</b><div class="meta">${esc(t.format)} • ${esc(t.status||'Open')} • ${communityDb.registrations.filter(r=>r.tournamentId===t.id).length} registered</div></div><div class="tour-actions"><button class="small" onclick="tourManage('${t.id}')">Manage</button></div></div>`).join('')}</div></section></div><section class="tour-admin-card" style="margin-top:18px"><span class="eyebrow">RESULT REVIEW</span><h3>Pending Match Results</h3>${pending.map(x=>`<div class="tour-list-row"><div><b>${esc(x.t.title)} • Match #${esc(x.m.number)}</b><div class="meta">Winner submitted: ${esc(communityDb.accounts.find(a=>a.id===x.m.submission.winner)?.ign||'Unknown')} • ${esc(x.m.submission.status)}</div></div><div class="tour-actions"><button class="small accent" onclick="ownerApproveResult('${x.t.id}','${x.m.id}')">Approve</button><button class="small danger" onclick="ownerRejectResult('${x.t.id}','${x.m.id}')">Reject</button></div></div>`).join('')||'<p class="muted">No pending results.</p>'}</section>`;
}
function tourAdminDenied(){return `<div class="tour-empty"><b>Owner access only.</b><p>The Tournament Admin is restricted to the Squad Owner.</p><button class="small accent" onclick="login()">Open Squad Portal</button></div>`}

function addSquadNotification(type,title,body,audienceId=null){db.notifications=db.notifications||[];db.notifications.unshift({id:'SN'+Date.now()+Math.random().toString(36).slice(2,7),type,title,body,audienceId,time:new Date().toISOString(),read:false});db.notifications=db.notifications.slice(0,100);save();if(current&&String(current.id)===String(audienceId))sendNotification(title,body);}
function squadNotificationBarHtml(){const notes=(db.notifications||[]).filter(n=>n.audienceId==null||(current&&String(n.audienceId)===String(current.id))).slice(0,20);return `<div id="squadNotificationBar" class="notification-bar ${notes.length?'':'empty'}"><div class="notification-bar-head"><div><span class="eyebrow">DARK SYSTEM</span><h3>Notifications</h3><p class="muted notification-subtitle">${notes.filter(n=>!n.read).length?notes.filter(n=>!n.read).length+' unread':'All caught up'}</p></div><div class="notification-head-actions"><button type="button" class="ghost small" onclick="markSquadNotificationsRead()">Mark all read</button><button type="button" class="ghost small notification-close" aria-label="Close notifications" onclick="closeSquadNotifications()">×</button></div></div>${notes.map(n=>`<article class="notification-item ${n.read?'read':'unread'}" onclick="markSquadNotificationRead('${esc(n.id)}')"><div class="notification-dot">•</div><div><b>${esc(n.title)}</b><p>${esc(n.body)}</p><small>${fmt(n.time)}</small></div>${n.read?'':'<span class="notification-unread-dot"></span>'}</article>`).join('')||'<p class="muted">No notifications yet.</p>'}</div>`;}
function toggleSquadNotificationBar(){const host=document.querySelector('.workspace');if(!host)return;let bar=document.getElementById('squadNotificationBar');if(bar){bar.remove();return;}host.insertAdjacentHTML('afterbegin',squadNotificationBarHtml());}
function closeSquadNotifications(){document.getElementById('squadNotificationBar')?.remove();}
function markSquadNotificationRead(id){const n=(db.notifications||[]).find(x=>String(x.id)===String(id));if(!n)return;if(n.audienceId!=null&&(!current||String(n.audienceId)!==String(current.id)))return;n.read=true;save();const bar=document.getElementById('squadNotificationBar');if(bar)bar.outerHTML=squadNotificationBarHtml();}
function markSquadNotificationsRead(){(db.notifications||[]).forEach(n=>{if(n.audienceId==null||(current&&String(n.audienceId)===String(current.id)))n.read=true;});save();const bar=document.getElementById('squadNotificationBar');if(bar)bar.outerHTML=squadNotificationBarHtml();refreshPortalNavLock();}

function addCommunityNotification(type,title,body,audienceId=null){
  communityDb.notifications=communityDb.notifications||[];
  communityDb.notifications.unshift({id:'N'+Date.now()+Math.random().toString(36).slice(2,7),type,title,body,audienceId,time:new Date().toISOString(),read:false});
  communityDb.notifications=communityDb.notifications.slice(0,100);
  saveCommunity();
  if(typeof sendNotification==='function') sendNotification(title,body);

  // Email delivery is opt-in per account and requires a server-side email provider.
  const audience = audienceId ? (communityDb.accounts||[]).filter(a=>String(a.id)===String(audienceId)) : (communityDb.accounts||[]);
  audience.forEach(a=>emailNotificationTo(a,title,body));
}
function purgeExpiredCancelledTournaments(){
  const now=Date.now();
  const expired=(communityDb.tournaments||[]).filter(t=>String(t.status||'').toLowerCase()==='cancelled' && t.cancelledAt && now-new Date(t.cancelledAt).getTime()>=30*60*1000);
  if(!expired.length)return false;
  expired.forEach(t=>{
    communityDb.registrations=(communityDb.registrations||[]).filter(r=>String(r.tournamentId)!==String(t.id));
    addCommunityNotification('removed','Tournament permanently removed','A previously cancelled tournament has been permanently removed after its 30-minute reinstatement window expired.');
  });
  const ids=new Set(expired.map(t=>String(t.id)));
  communityDb.tournaments=communityDb.tournaments.filter(t=>!ids.has(String(t.id)));
  saveCommunity();
  return true;
}
function cancelledRemainingMs(t){
  if(!t?.cancelledAt)return 0;
  return Math.max(0,30*60*1000-(Date.now()-new Date(t.cancelledAt).getTime()));
}
function cancelledRemainingText(t){
  const ms=cancelledRemainingMs(t); if(!ms)return 'Expired';
  const mins=Math.floor(ms/60000), secs=Math.floor((ms%60000)/1000);
  return `${mins}m ${String(secs).padStart(2,'0')}s remaining`;
}
function reinstateTournament(id){
  if(!ownerTournamentAccess())return error('OWNER ONLY','Only the Squad Owner can reinstate a cancelled tournament.');
  purgeExpiredCancelledTournaments();
  const t=communityDb.tournaments.find(x=>String(x.id)===String(id));
  if(!t)return error('TOURNAMENT NOT FOUND','The reinstatement window has expired or the tournament no longer exists.');
  if(String(t.status||'').toLowerCase()!=='cancelled')return error('NOT CANCELLED','This tournament is not currently cancelled.');
  if(!cancelledRemainingMs(t))return error('WINDOW EXPIRED','The 30-minute reinstatement window has expired.');
  t.status='Open'; t.registrationOpen=true; t.cancelledAt=null; t.cancelledBy=null;
  (communityDb.registrations||[]).filter(r=>String(r.tournamentId)===String(id)).forEach(r=>{r.status='Registered';});
  addCommunityNotification('reinstated','Tournament reinstated',`${t.title} has been reinstated. Registration is open again.`);
  saveCommunity(); close(); renderTournamentPage();
}
function scheduleCancelledPurge(){
  clearInterval(window.__darkSystemCancelTimer);
  window.__darkSystemCancelTimer=setInterval(()=>{if(purgeExpiredCancelledTournaments() && typeof renderTournamentPage==='function' && !document.getElementById('tournamentPage')?.classList.contains('hidden'))renderTournamentPage();},1000);
}
scheduleCancelledPurge();

function cancelTournamentConfirm(id){
  if(!ownerTournamentAccess()) return error('OWNER ONLY','Only the Squad Owner can cancel a tournament.');
  const t=communityDb.tournaments.find(x=>String(x.id)===String(id));
  if(!t) return error('TOURNAMENT NOT FOUND','This tournament could not be found.');
  if(['Cancelled','Completed'].includes(t.status)) return error('CANNOT CANCEL','This tournament is already '+t.status.toLowerCase()+'.');
  show(`<div class="setup-lock"><div class="setup-icon">!</div><span class="eyebrow">CANCEL TOURNAMENT</span><h2>Do you confirm to cancel this tournament?</h2><p class="muted">You are about to cancel <b>${esc(t.title)}</b>. Registration will close and registered players will see that the tournament was cancelled.</p><div class="actions"><button class="danger" id="confirmCancelTournament">Yes, Continue</button><button class="ghost" id="abortCancelTournament">No, Keep Tournament</button></div></div>`);
  document.getElementById('abortCancelTournament')?.addEventListener('click',close);
  document.getElementById('confirmCancelTournament')?.addEventListener('click',()=>cancelTournamentCode(id));
}
function cancelTournamentCode(id){
  const owner=db.members.find(m=>m.role==='Squad Owner');
  if(!owner) return error('OWNER ACCOUNT NOT FOUND','The Squad Owner account could not be verified.');
  show(`<div class="login-wrap"><span class="eyebrow">OWNER VERIFICATION</span><h2>Enter Squad Owner Access Code</h2><p class="muted">For security, cancelling a tournament requires the Squad Owner access code.</p><form id="cancelTournamentForm" class="form"><label class="full">Squad Owner Access Code<input id="cancelOwnerCode" type="password" required autocomplete="current-password" placeholder="Enter owner access code"></label><div class="actions"><button class="primary">Verify & Cancel Tournament</button><button type="button" class="ghost" id="cancelTournamentCodeBack">Back</button></div></form></div>`);
  document.getElementById('cancelTournamentCodeBack')?.addEventListener('click',()=>cancelTournamentConfirm(id));
  document.getElementById('cancelTournamentForm')?.addEventListener('submit',e=>{
    e.preventDefault();
    if(String(cancelOwnerCode.value).trim().toUpperCase()!==String(owner.accessCode||'').trim().toUpperCase()) return error('ACCESS DENIED','The Squad Owner access code is incorrect.');
    const t=communityDb.tournaments.find(x=>String(x.id)===String(id));
    if(!t) return error('TOURNAMENT NOT FOUND','This tournament could not be found.');
    t.status='Cancelled'; t.registrationOpen=false; t.cancelledAt=new Date().toISOString(); t.cancelledBy=owner.id;
    communityDb.registrations.forEach(r=>{if(String(r.tournamentId)===String(id)) r.status='Tournament Cancelled';});
    addCommunityNotification('cancelled','Tournament cancelled',`${t.title} has been cancelled. Registered members have been notified. You have 30 minutes to reinstate it.`);
    (t.matches||[]).forEach(m=>{m.cancelled=true;});
    saveCommunity(); close(); renderTournamentPage();
    show(`<div class="setup-lock"><div class="setup-icon">✓</div><span class="eyebrow">TOURNAMENT CANCELLED</span><h2>${esc(t.title)}</h2><p class="muted">The tournament has been cancelled successfully. Registration is closed and affected registrations have been marked as cancelled.</p><div class="actions"><button class="primary" onclick="close();tourSetView('admin')">Done</button></div></div>`);
  });
}
function tourManage(id){
  if(!tournamentAdminAccess()) return error('ACCESS DENIED','You do not have Tournament Manager permission.');
  const t=communityDb.tournaments.find(x=>x.id===id);if(!t)return;
  const regs=communityDb.registrations.filter(r=>r.tournamentId===id);
  show(`<div class="login-wrap"><span class="eyebrow">TOURNAMENT ADMIN</span><h2>${esc(t.title)}</h2><p class="muted">${regs.length} registered • ${t.matches?.length||0} matches generated • Status: <b>${esc(t.status||'Open')}</b></p><div class="tour-list">${regs.map(r=>`<div class="tour-list-row"><div><b>${esc(r.ign)}</b><div class="meta">ID ${esc(r.gameId)} • Server ${esc(r.serverId)}</div></div><span class="tour-chip">${esc(r.status)}</span></div>`).join('')||'<p class="muted">No registrations yet.</p>'}</div><div class="actions"><button class="primary" ${regs.length<2?'disabled':''} ${t.status==='Cancelled'?'disabled':''} onclick="close();generateBracket('${t.id}')">${t.matches?.length?'Regenerate Bracket':'Generate Bracket'}</button>${ownerTournamentAccess()&&t.status!=='Cancelled'&&t.status!=='Completed'?`<button class="danger" onclick="cancelTournamentConfirm('${t.id}')">Cancel Tournament</button>`:''}<button class="ghost" onclick="close()">Close</button></div></div>`);
}
async function generateBracket(tid){
  if(!tournamentAdminAccess()) return error('ACCESS DENIED','You do not have Tournament Manager permission.');
  try{
    if(DARK_BACKEND){
      const data=await api('/api/tournaments/bracket',{method:'POST',body:JSON.stringify({tournamentId:String(tid)})});
      if(data.tournament){const i=communityDb.tournaments.findIndex(x=>String(x.id)===String(tid));if(i>=0)communityDb.tournaments[i]=data.tournament;else communityDb.tournaments.push(data.tournament);}
    }else{
      const t=communityDb.tournaments.find(x=>x.id===tid);if(!t)return;const regs=communityDb.registrations.filter(r=>r.tournamentId===tid);if(regs.length<2)return error('NOT ENOUGH PLAYERS','At least two registered players are needed.');
      const ids=regs.map(r=>r.accountId);let size=1;while(size<ids.length)size*=2;while(ids.length<size)ids.push(null);t.matches=[];let currentRound=ids.slice();let round=1;let matchNo=1;while(currentRound.length>1){const next=[];for(let i=0;i<currentRound.length;i+=2){const a=currentRound[i],b=currentRound[i+1];const mid=`${tid}-M${matchNo++}`;t.matches.push({id:mid,number:matchNo-1,round,player1:a,player2:b,winner:a&&!b?a:b&&!a?b:null,submission:null});next.push(null)}currentRound=next;round++;}
      let r=1;while(r<round){const prev=t.matches.filter(m=>m.round===r);const next=t.matches.filter(m=>m.round===r+1);prev.filter(m=>m.winner).forEach(m=>{const target=next.find(x=>!x.player1||!x.player2);if(target){if(!target.player1)target.player1=m.winner;else if(!target.player2)target.player2=m.winner;}});r++;}
      saveCommunity();
    }
    renderTournamentPage();show(`<div class="setup-lock"><div class="setup-icon">✓</div><span class="eyebrow">BRACKET GENERATED</span><h2>Bracket ready</h2><p class="muted">The tournament bracket is ready. Players can now see their matches in Match Center.</p><div class="actions"><button class="primary" onclick="close();tourSetView('matches')">Open Match Center</button></div></div>`);
  }catch(err){error('BRACKET GENERATION FAILED',err.message)}
}

async function ownerApproveResult(tid,mid){
  if(!tournamentAdminAccess())return error('ACCESS DENIED','You do not have Tournament Manager permission.');
  try{if(DARK_BACKEND){const r=await api('/api/tournaments/result-review',{method:'POST',body:JSON.stringify({action:'approve',tournamentId:String(tid),matchId:String(mid)})});if(r.tournament){const i=communityDb.tournaments.findIndex(x=>String(x.id)===String(tid));if(i>=0)communityDb.tournaments[i]=r.tournament;}}else{const t=communityDb.tournaments.find(x=>x.id===tid),m=t?.matches?.find(x=>String(x.id)===String(mid));if(!m?.submission)return;m.winner=m.submission.winner;m.submission.status='Owner Approved';awardTournamentPoints(t,m);advanceMatch(t,m);saveCommunity();}renderTournamentPage();}catch(err){error('RESULT APPROVAL FAILED',err.message)}
}
async function ownerRejectResult(tid,mid){
  if(!tournamentAdminAccess())return error('ACCESS DENIED','You do not have Tournament Manager permission.');
  try{if(DARK_BACKEND){const r=await api('/api/tournaments/result-review',{method:'POST',body:JSON.stringify({action:'reject',tournamentId:String(tid),matchId:String(mid)})});if(r.tournament){const i=communityDb.tournaments.findIndex(x=>String(x.id)===String(tid));if(i>=0)communityDb.tournaments[i]=r.tournament;}}else{const t=communityDb.tournaments.find(x=>x.id===tid),m=t?.matches?.find(x=>String(x.id)===String(mid));if(!m?.submission)return;m.submission=null;saveCommunity();}renderTournamentPage();}catch(err){error('RESULT REJECTION FAILED',err.message)}
}

/* Replace the public tournament/leaderboard/hall previews with live tournament data. */
const _oldRenderPublic=renderPublic;
renderPublic=function(){
  _oldRenderPublic();processCommunitySeason();
  const lp=document.querySelector('#leaderboard .leaderboard-preview');if(lp){const rows=communityLeaderboardRows().slice(0,10);const season=getCurrentCommunitySeason();lp.innerHTML='<div class="leader-row head"><span>#</span><span>PLAYER</span><span>PARTICIPATION</span><span>POINTS</span></div>'+(rows.map((x,i)=>`<div class="leader-row"><b>${String(i+1).padStart(2,'0')}</b><strong>${esc(x.a.ign)}</strong><span>${x.wins} wins • ${x.losses} losses • ${x.events} events</span><b>${x.p}</b></div>`).join('')||'<div class="leader-row"><b>01</b><strong>No scores yet</strong><span>Participate in community events and tournaments</span><b>0</b></div>');const badge=document.querySelector('#leaderboard .coming-badge');if(badge)badge.textContent=`${season.season} • ACTIVE SEASON`;}
  const hg=document.querySelector('#hall .hall-grid');if(hg){const season=communityDb.seasonHallOfFame||[];const legacy=communityDb.hallOfFame||[];const cards=season.slice().reverse().map(h=>`<article><span>🏆</span><h3>${esc(h.season)} • ${esc(h.position)} Place</h3><p><b>${esc(h.ign)}</b> finished ${esc(h.position)} in the Community Leaderboard with ${esc(h.points)} points.</p><small>${esc(h.period||'')}</small></article>`);if(!cards.length)cards.push(...legacy.slice().reverse().map(h=>`<article><span>🏆</span><h3>${esc(h.title)}</h3><p><b>Champion:</b> ${esc(communityDb.accounts.find(a=>String(a.id)===String(h.champion))?.ign||'Unknown')}</p><small>${esc(h.date||'')}</small></article>`));hg.innerHTML=cards.join('')||'<article><span>🏆</span><h3>Hall of Fame</h3><p>The top three Community Leaderboard finishers from each MLBB season will appear here.</p></article>';}
};
function mlbbSeasonCalendar(){return [{season:'S40',start:'2026-03-11T00:00:00Z',end:'2026-06-17T08:00:00Z'},{season:'S41',start:'2026-06-17T00:00:00Z',end:'2026-09-16T08:00:00Z'},{season:'S42',start:'2026-09-16T08:00:00Z',end:'2026-12-16T08:00:00Z'},{season:'S43',start:'2026-12-16T08:00:00Z',end:'2027-03-17T08:00:00Z'},{season:'S44',start:'2027-03-17T08:00:00Z',end:'2027-06-16T08:00:00Z'}];}
function getCurrentCommunitySeason(now=new Date()){const t=now.getTime(),cal=mlbbSeasonCalendar();const found=cal.find(s=>t>=new Date(s.start).getTime()&&t<new Date(s.end).getTime());if(found)return found;let last=cal[cal.length-1],idx=Number(last.season.slice(1)),start=new Date(last.start),end=new Date(last.end);while(t>=end.getTime()){idx++;start=end;end=new Date(start.getTime()+91*86400000);last={season:'S'+idx,start:start.toISOString(),end:end.toISOString()};}return last;}
function ensureCommunitySeason(){const season=getCurrentCommunitySeason();if(!communityDb.currentSeason){communityDb.currentSeason=season.season;saveCommunity();return;}if(communityDb.currentSeason!==season.season)finalizeCommunitySeason(communityDb.currentSeason,season);}
function communityTournamentStats(id){let wins=0,losses=0;communityDb.tournaments.forEach(t=>{const season=getCurrentCommunitySeason(new Date(`${t.date||'1970-01-01'}T${t.time||'00:00'}:00Z`)).season;if(season!==communityDb.currentSeason)return;(t.matches||[]).forEach(m=>{if(!m.winner)return;if(String(m.winner)===String(id))wins++;else if(String(m.player1)===String(id)||String(m.player2)===String(id))losses++;});});return{wins,losses};}
function communityLeaderboardRows(){return(communityDb.accounts||[]).map(a=>{const stats=communityTournamentStats(a.id),events=(communityDb.eventParticipation||[]).filter(x=>String(x.accountId)===String(a.id)&&x.season===communityDb.currentSeason).length;return{a,p:Number((communityDb.seasonPoints||{})[a.id]||0),wins:stats.wins,losses:stats.losses,events};}).sort((a,b)=>b.p-a.p||b.wins-a.wins||String(a.a.ign).localeCompare(String(b.a.ign)));}
function processCommunitySeason(){ensureCommunitySeason();}
function finalizeCommunitySeason(oldSeason,newSeason){const rows=communityLeaderboardRows(),top=rows.slice(0,3);communityDb.seasonHistory=communityDb.seasonHistory||[];communityDb.seasonHallOfFame=communityDb.seasonHallOfFame||[];communityDb.seasonHistory.push({season:oldSeason,endedAt:new Date().toISOString(),standings:rows.map((x,i)=>({accountId:x.a.id,ign:x.a.ign,position:i+1,points:x.p}))});top.forEach((x,i)=>communityDb.seasonHallOfFame.push({season:oldSeason,position:i+1,ign:x.a.ign,accountId:x.a.id,points:x.p,period:oldSeason}));(communityDb.accounts||[]).forEach(a=>{const row=rows.find(x=>String(x.a.id)===String(a.id)),pos=row?rows.indexOf(row)+1:0;const body=pos&&pos<=3?`Season ${oldSeason} has ended. You finished #${pos} with ${row.p} points. Congratulations — you will appear in the Dark System Hall of Fame.`:`Season ${oldSeason} has ended. You finished ${pos?`#${pos}`:'without a ranked position'} with ${row?.p||0} points. Keep participating — the next season is a fresh opportunity to climb the Community Leaderboard.`;addCommunityNotification('season','Community Season Results',body,String(a.id));});communityDb.seasonPoints={};communityDb.eventParticipation=[];communityDb.currentSeason=newSeason.season;saveCommunity();}
function recordEventParticipation(eventId){if(!communityCurrent)return communityAuth();ensureCommunitySeason();if((communityDb.eventParticipation||[]).some(x=>String(x.eventId)===String(eventId)&&String(x.accountId)===String(communityCurrent.id)&&x.season===communityDb.currentSeason))return error('ALREADY RECORDED','Your participation for this event has already been recorded.');communityDb.eventParticipation.push({id:Date.now(),eventId,accountId:communityCurrent.id,season:communityDb.currentSeason,time:new Date().toISOString()});communityDb.seasonPoints[communityCurrent.id]=(communityDb.seasonPoints[communityCurrent.id]||0)+50;addCommunityNotification('participation','Event participation recorded','You earned 50 Community Leaderboard points for participating in this event.',String(communityCurrent.id));saveCommunity();renderPublic();close();show(`<div class="setup-lock"><div class="setup-icon">✓</div><span class="eyebrow">PARTICIPATION RECORDED</span><h2>+50 Community Points</h2><p class="muted">Your participation has been added to the ${esc(communityDb.currentSeason)} Community Leaderboard.</p><div class="actions"><button class="primary" onclick="close()">Done</button></div></div>`);}


/* V5.10 fixes: confirmation-before-registration, reliable Done action,
   explicit Owner tournament access, and automatic matchmaking by format. */
function getAccount(id){ return communityDb.accounts.find(a=>String(a.id)===String(id)); }
function registrationPreview(t){
  return `<div class="profile-data">
    <div><small>IGN</small><b>${esc(communityCurrent?.ign||'')}</b></div>
    <div><small>GAME ID</small><b>${esc(communityCurrent?.gameId||'')}</b></div>
    <div><small>SERVER ID</small><b>${esc(communityCurrent?.serverId||'')}</b></div>
    <div><small>EMAIL</small><b>${esc(communityCurrent?.email||'')}</b></div>
  </div>`;
}

registerFromTournament = function(id){
  const t=communityDb.tournaments.find(x=>x.id===id);
  if(!t||t.status!=='Open'||t.registrationOpen===false) return error('REGISTRATION CLOSED','This tournament is not open for registration.');
  if(!communityCurrent){ pendingTournamentId=id; communityAuth(); return; }
  if(communityDb.registrations.some(r=>r.accountId===communityCurrent.id&&r.tournamentId===id)) return error('ALREADY REGISTERED','You are already registered for this tournament.');
  const count=communityDb.registrations.filter(r=>r.tournamentId===id).length;
  if(Number(t.slots)&&count>=Number(t.slots)) return error('TOURNAMENT FULL','All available registration slots have been filled.');
  show(`<div class="login-wrap"><span class="eyebrow">CONFIRM REGISTRATION</span><h2>Register for ${esc(t.title)}</h2><p class="muted">Please confirm that this is the profile you want to use for this MLBB tournament.</p>${registrationPreview(t)}<div class="profile-data"><div><small>FORMAT</small><b>${esc(t.format)}</b></div><div><small>DATE</small><b>${esc(t.date||'TBA')}</b></div><div><small>START</small><b>${esc(t.time||'TBA')}</b></div><div><small>PRIZE</small><b>${esc(t.reward||'Rewards')}</b></div></div><div class="actions"><button class="primary" id="confirmTournamentRegistration">Confirm Registration</button><button class="ghost" id="cancelTournamentRegistration">Cancel</button></div></div>`);
  document.getElementById('cancelTournamentRegistration').onclick=close;
  const confirmBtn=document.getElementById('confirmTournamentRegistration');
  const cancelBtn=document.getElementById('cancelTournamentRegistration');
  if(confirmBtn) confirmBtn.addEventListener('click',()=>completeTournamentRegistration(t.id));
  if(cancelBtn) cancelBtn.addEventListener('click',()=>close());
};

function completeTournamentRegistration(id){
  const t=communityDb.tournaments.find(x=>x.id===id); if(!t||!communityCurrent)return;
  if(t.status!=='Open'||t.registrationOpen===false){ close(); return error('REGISTRATION CLOSED','This tournament is no longer open for registration.'); }
  if(communityDb.registrations.some(r=>r.accountId===communityCurrent.id&&r.tournamentId===id)){ close(); return error('ALREADY REGISTERED','You are already registered for this tournament.'); }
  const count=communityDb.registrations.filter(r=>r.tournamentId===id).length;
  const slots=Number(t.slots||0);
  if(slots && count>=slots){ close(); autoMatchmakeIfReady(t); return error('TOURNAMENT FULL','All available registration slots have been filled. Registration is closed.'); }
  communityDb.registrations.push({id:Date.now(),accountId:communityCurrent.id,tournamentId:id,ign:communityCurrent.ign,gameId:communityCurrent.gameId,serverId:communityCurrent.serverId,status:'Registered',registeredAt:new Date().toISOString()});
  const newCount=count+1;
  saveCommunity();
  close();
  autoMatchmakeIfReady(t);
  const full=slots>0 && newCount>=slots;
  show(`<div class="setup-lock"><div class="setup-icon">✓</div><span class="eyebrow">REGISTRATION COMPLETE</span><h2>${esc(t.title)}</h2><p class="muted">${esc(communityCurrent.ign)}, your registration has been confirmed.${full?' The registration limit has been reached, so registration is now closed and matchmaking has started automatically.':' You can follow your matches from Match Center.'}</p><div class="actions"><button type="button" class="primary done-action" id="registrationDoneBtn" aria-label="Finish registration">Done</button></div></div>`);
  const done=document.getElementById('registrationDoneBtn');
  if(done) done.addEventListener('click',()=>{ close(); renderTournamentPage(); });
}

registerCommunityTournament = function(id){ return registerFromTournament(id); };

function autoMatchmakeIfReady(t){
  const regs=communityDb.registrations.filter(r=>r.tournamentId===t.id);
  const slots=Number(t.slots||0);
  const needed=slots>0?slots:2;
  if(regs.length<needed || t.bracketReady) return false;
  if(slots>0 && regs.length>slots) return false;
  const groupSize=(t.format==='1v1'||t.format==='1v1')?1:(t.format==='2v2'?2:5);
  if(regs.length<groupSize*2){
    t.registrationOpen=false;
    t.status='Full — Waiting for valid team size';
    saveCommunity();
    return false;
  }
  if(t.format!=='1v1' && regs.length%groupSize!==0){
    t.registrationOpen=false;
    t.status='Full — Waiting for valid team size';
    saveCommunity();
    return false;
  }
  t.registrationOpen=false;
  t.status='Matched';
  buildAutoMatches(t,regs);
  saveCommunity();
  return true;
}
function shuffleArray(arr){
  const a=arr.slice(); for(let i=a.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[a[i],a[j]]=[a[j],a[i]];} return a;
}
function buildAutoMatches(t,regs){
  const shuffled=shuffleArray(regs);
  const groupSize=t.format==='1v1'?1:(t.format==='2v2'?2:5);
  if(t.format!=='1v1' && shuffled.length%groupSize!==0) return false;
  const groups=[];
  for(let i=0;i<shuffled.length;i+=groupSize){
    const g=shuffled.slice(i,i+groupSize).map(r=>r.accountId);
    if(g.length===groupSize) groups.push(g);
  }
  t.matches=[];
  t.teams=[];
  if(t.format==='1v1'){
    let n=1;
    for(let i=0;i<groups.length;i+=2){
      const a=groups[i]?.[0],b=groups[i+1]?.[0];
      if(!a)continue;
      t.matches.push({id:`${t.id}-M${n}`,number:n,round:1,player1:a,player2:b||null,side1:[a],side2:b?[b]:[],winner:b?null:a,submission:null});
      n++;
    }
  } else {
    t.teams=groups.map((members,i)=>({id:`${t.id}-T${i+1}`,name:`${t.format==='2v2'?'Team':'Squad'} ${i+1}`,members}));
    let n=1;
    for(let i=0;i<t.teams.length;i+=2){
      const a=t.teams[i],b=t.teams[i+1];
      if(!a)continue;
      t.matches.push({id:`${t.id}-M${n}`,number:n,round:1,player1:a.members[0],player2:b?b.members[0]:null,side1:a.members,side2:b?b.members:[],team1:a.id,team2:b?.id||null,winner:b?null:a.members[0],submission:null});
      n++;
    }
    t.matchmaking={format:t.format,groupSize,teams:t.teams.map(x=>({id:x.id,name:x.name,members:x.members}))};
  }
  generateBracketFromMatches(t);
  return true;
}
function generateBracketFromMatches(t){
  const first=t.matches.slice(); let current=first.filter(m=>m.player1&&m.player2).map(m=>m.winner||null); let round=2; let prior=first.length;
  /* Keep a clean round structure for the prototype; later rounds are created as winners advance. */
  t.bracketReady=true; t.registrationOpen=false; t.status='Matched';
}

/* Owner is identified by the private Squad Portal session, not by a public Community account. */
function isTournamentManager(){ return !!(current && Array.isArray(communityDb.tournamentManagers) && communityDb.tournamentManagers.map(String).includes(String(current.id))); }
function tournamentAdminAccess(){ return !!(current && (current.role==='Squad Owner' || isTournamentManager())); }
function ownerTournamentAccess(){ return !!(current && current.role==='Squad Owner'); }
function openOwnerTournamentCenter(){
  if(!tournamentAdminAccess()) return error('ACCESS DENIED','Tournament administration is restricted to the Dark System Owner and delegated Tournament Managers.');
  openTournamentPage(); tournamentView='admin'; renderTournamentPage();
}
function openTournamentAdminCenter(){ return openOwnerTournamentCenter(); }

/* Add a direct Tournament Center control to the Owner dashboard. */
const _oldOverviewV510=overview;
overview=function(owner,leader){
  let html=_oldOverviewV510(owner,leader);
  if(owner){
    html=html.replace('</section>\n  </div>`','</section>\n    <section class="panel" style="margin-top:18px"><div class="section-head"><div><span class="eyebrow">OWNER CONTROL</span><h3>Tournament Center</h3><p class="muted">Create tournaments, close registration, auto-match players and review results.</p></div><button class="small accent" onclick="openOwnerTournamentCenter()">Open Tournament Admin →</button></div></section>\n  </div>`');
  }
  return html;
};

/* Give the Owner a clear testing path in the admin page and make auto-match visible. */
const _oldTourAdmin= tourAdmin;
tourAdmin=function(){
  const base=_oldTourAdmin();
  const help=`<section class="tour-admin-card" style="margin-bottom:18px"><span class="eyebrow">OWNER ACCESS</span><h3>You are the Squad Owner</h3><p class="muted">Tournament administration is available because you entered through the private Squad Portal with the Owner account. Community accounts never receive these controls.</p></section>`;
  return help+base;
};

/* Override Manage dialog with automatic matchmaking controls. */
tourManage=function(id){
  const t=communityDb.tournaments.find(x=>x.id===id); if(!t)return;
  const regs=communityDb.registrations.filter(r=>r.tournamentId===id);
  const slots=Number(t.slots||0);
  const full=slots>0 && regs.length>=slots;
  const matched=!!t.bracketReady;
  show(`<div class="login-wrap"><span class="eyebrow">TOURNAMENT ADMIN</span><h2>${esc(t.title)}</h2><p class="muted">${regs.length}${slots?` / ${slots}`:''} registered • ${esc(t.format)} • ${matched?'Matchmaking generated':'Registration open'}</p><div class="tour-list">${regs.map((r,i)=>`<div class="tour-list-row"><div><b>${i+1}. ${esc(r.ign)}</b><div class="meta">ID ${esc(r.gameId)} • Server ${esc(r.serverId)}</div></div><span class="tour-chip">${esc(r.status)}</span></div>`).join('')||'<p class="muted">No registrations yet.</p>'}</div><div class="actions"><button class="primary" id="manualMatchBtn" ${regs.length<2||matched?'disabled':''}>${matched?'Matchmaking Complete':'Run Matchmaking Now'}</button><button class="ghost" id="closeManageBtn">Close</button></div><p class="muted" style="margin-top:12px">${full?'Registration is full and automatically closed. Matchmaking is triggered automatically.':'Players will be matched automatically when the total slot capacity is reached.'}</p></div>`);
  const closeBtn=document.getElementById('closeManageBtn');
  const matchBtn=document.getElementById('manualMatchBtn');
  if(closeBtn) closeBtn.addEventListener('click',()=>close());
  if(matchBtn) matchBtn.addEventListener('click',()=>{ if(!tournamentAdminAccess()) return error('ACCESS DENIED','You do not have Tournament Manager permission.'); const ok=autoMatchmakeIfReady(t); if(!ok) return error('NOT READY','Automatic matchmaking requires the tournament to reach its full configured capacity and a valid team size.'); close(); renderTournamentPage(); show(`<div class="setup-lock"><div class="setup-icon">✓</div><span class="eyebrow">MATCHMAKING COMPLETE</span><h2>${esc(t.title)}</h2><p class="muted">Registration is closed and the matches have been generated automatically.</p><div class="actions"><button type="button" class="primary" id="openMatchesBtn">Open Matches</button></div></div>`); const b=document.getElementById('openMatchesBtn'); if(b)b.addEventListener('click',()=>{close();tourSetView('matches')}); });
};

/* ================= V6.2: OWNER + DELEGATED TOURNAMENT MANAGERS ================= */
async function grantTournamentManager(memberId){
  if(!ownerTournamentAccess()) return error('OWNER ONLY','Only the Dark System Owner can grant Tournament Manager access.');
  const m=db.members.find(x=>String(x.id)===String(memberId));
  if(!m || !['Squad Leader','Assistant Squad Leader'].includes(m.role)) return error('INVALID CANDIDATE','Only Squad Leaders and Assistant Squad Leaders can be given Tournament Manager access.');
  try{if(DARK_BACKEND){await api('/api/tournament-managers',{method:'POST',body:JSON.stringify({action:'grant',memberId:String(memberId)})});await backendHydrate();}else{if(!communityDb.tournamentManagers.includes(m.id)) communityDb.tournamentManagers.push(m.id);saveCommunity();}close();renderTournamentPage();show(`<div class="setup-lock"><div class="setup-icon">✓</div><span class="eyebrow">PERMISSION GRANTED</span><h2>${esc(m.ign)} is now a Tournament Manager</h2><p class="muted">Tournament administration access has been granted.</p><div class="actions"><button class="primary" onclick="close();renderTournamentPage()">Done</button></div></div>`);}catch(err){error('PERMISSION UPDATE FAILED',err.message)}
}
async function revokeTournamentManager(memberId){
  if(!ownerTournamentAccess()) return error('OWNER ONLY','Only the Dark System Owner can revoke Tournament Manager access.');
  const m=db.members.find(x=>String(x.id)===String(memberId));
  try{if(DARK_BACKEND){await api('/api/tournament-managers',{method:'POST',body:JSON.stringify({action:'revoke',memberId:String(memberId)})});await backendHydrate();}else{communityDb.tournamentManagers=communityDb.tournamentManagers.filter(id=>String(id)!==String(memberId));saveCommunity();}close();renderTournamentPage();if(m)show(`<div class="setup-lock"><div class="setup-icon">✓</div><span class="eyebrow">PERMISSION REVOKED</span><h2>${esc(m.ign)} is no longer a Tournament Manager</h2><p class="muted">Tournament administration access has been removed.</p><div class="actions"><button class="primary" onclick="close();renderTournamentPage()">Done</button></div></div>`);}catch(err){error('PERMISSION UPDATE FAILED',err.message)}
}

function tournamentManagerPanel(){
  if(!ownerTournamentAccess()) return '';
  const candidates=db.members.filter(m=>['Squad Leader','Assistant Squad Leader'].includes(m.role));
  // Remove stale manager grants from anyone who is no longer a Squad Leader.
  const leaderIds=new Set(candidates.map(m=>String(m.id)));
  communityDb.tournamentManagers=communityDb.tournamentManagers.filter(id=>leaderIds.has(String(id)));
  saveCommunity();
  return `<section class="tour-admin-card" style="margin-top:18px"><span class="eyebrow">DARK SYSTEM OWNER</span><h3>Tournament Manager Access</h3><p class="muted">Squad Leaders and Assistant Squad Leaders are eligible. Squad Members cannot be granted Tournament Manager access.</p><div class="tour-list">${candidates.map(m=>{const active=communityDb.tournamentManagers.includes(m.id);return `<div class="tour-list-row"><div><b>${esc(m.ign)}</b><div class="meta">${esc(m.role)} • ${active?'Tournament Manager':'No Tournament Admin access'}</div></div><div class="tour-actions">${active?`<button class="small danger" onclick="revokeTournamentManager('${m.id}')">Revoke</button>`:`<button class="small accent" onclick="grantTournamentManager('${m.id}')">Grant Access</button>`}</div></div>`}).join('')||'<p class="muted">No eligible squad members.</p>'}</div></section>`;
}
function tourManagerAdmin(){
  const pending=[];
  communityDb.tournaments.forEach(t=>(t.matches||[]).forEach(m=>{
    if(m.submission&&['Awaiting Confirmation','Disputed'].includes(m.submission.status)) pending.push({t,m});
  }));
  return `<div class="tour-manager-shell">
    <section class="tour-manager-hero">
      <div><span class="eyebrow">DELEGATED ACCESS</span><h2>Tournament Manager Portal</h2><p class="muted">You have been granted tournament-management permissions. This is a separate management workspace from the Squad Owner portal.</p></div>
      <div class="tour-manager-badge">TOURNAMENT MANAGER</div>
    </section>
    <div class="tour-stat-row"><div class="tour-stat-card"><small>TOURNAMENTS</small><b>${communityDb.tournaments.length}</b></div><div class="tour-stat-card"><small>REGISTRATIONS</small><b>${communityDb.registrations.length}</b></div><div class="tour-stat-card"><small>PENDING REVIEWS</small><b>${pending.length}</b></div><div class="tour-stat-card"><small>COMPLETED</small><b>${communityDb.tournaments.filter(t=>t.completed).length}</b></div></div>
    <div class="admin-grid">
      <section class="tour-admin-card manager-card"><span class="eyebrow">TOURNAMENT MANAGER</span><h3>Create Tournament</h3><form id="createTourForm" class="tour-form"><label>Title<input id="ntTitle" required placeholder="Dark System 1v1 Championship"></label><label>Format<select id="ntFormat"><option>1v1</option><option>5v5</option><option>2v2</option></select></label><label>Game<input value="Mobile Legends: Bang Bang" disabled></label><label>Date<input id="ntDate" type="date" required></label><label>Start Time<input id="ntTime" type="time" required></label><label>Registration Deadline<input id="ntDeadline" type="date"></label><label>Slots<input id="ntSlots" type="number" min="2" value="32" required></label><label>Prize / Reward<input id="ntReward" placeholder="₦10,000"></label><label class="full">Rules<textarea id="ntRules" required placeholder="Enter the tournament rules..."></textarea></label><label class="full">Description<textarea id="ntDesc" placeholder="Tournament description..."></textarea></label><div class="actions full"><button class="primary">Publish Tournament</button></div></form></section>
      <section class="tour-admin-card manager-card"><span class="eyebrow">MANAGE TOURNAMENTS</span><h3>Existing Tournaments</h3><div class="tour-list">${communityDb.tournaments.map(t=>`<div class="tour-list-row"><div><b>${esc(t.title)}</b><div class="meta">${esc(t.format)} • ${esc(t.status||'Open')} • ${communityDb.registrations.filter(r=>r.tournamentId===t.id).length} registered</div></div><div class="tour-actions"><button class="small" onclick="tourManage('${t.id}')">Manage</button></div></div>`).join('')}</div></section>
    </div>
    <section class="tour-admin-card manager-card" style="margin-top:18px"><span class="eyebrow">RESULT REVIEW</span><h3>Pending Match Results</h3>${pending.map(x=>`<div class="tour-list-row"><div><b>${esc(x.t.title)} • Match #${esc(x.m.number)}</b><div class="meta">${esc(x.m.submission.submitterResult||'Result')} • Winner submitted: ${esc(communityDb.accounts.find(a=>a.id===x.m.submission.winner)?.ign||'Unknown')} • ${esc(x.m.submission.status)} • Battle ID: ${esc(x.m.submission.battleId||'Not provided')}</div></div><div class="tour-actions"><button class="small accent" onclick="ownerApproveResult('${x.t.id}','${x.m.id}')">Approve</button><button class="small danger" onclick="ownerRejectResult('${x.t.id}','${x.m.id}')">Reject</button></div></div>`).join('')||'<p class="muted">No pending results.</p>'}</section>
    <section class="tour-manager-permissions"><b>Access boundary</b><p>You can manage tournaments and match results. Squad ownership, squad permissions and Tournament Manager grants remain unavailable to you.</p></section>
  </div>`;
}
const _v6BaseTourAdmin=tourAdmin;
tourAdmin=function(){
  if(isTournamentManager() && !ownerTournamentAccess()) return tourManagerAdmin();
  let base=_v6BaseTourAdmin();
  base=base.replace('OWNER CONTROL','TOURNAMENT CONTROL').replace('Owner access only.','Tournament Manager access.');
  const intro=tournamentAdminAccess()?`<section class="tour-admin-card" style="margin-bottom:18px"><span class="eyebrow">DARK SYSTEM OWNER</span><h3>Full Tournament Authority</h3><p class="muted">You are the Squad Owner. This workspace includes the full tournament system and delegated-access controls.</p></section>`:'';
  return intro+base+tournamentManagerPanel();
};

/* Managers can open the Tournament Admin from their private Squad dashboard too. */
const _v6BaseOverview=overview;
overview=function(owner,leader){
  let html=_v6BaseOverview(owner,leader);
  if(tournamentAdminAccess()) html=html.replace('</section>\n  </div>`','</section><section class="panel" style="margin-top:18px"><div class="section-head"><div><span class="eyebrow">TOURNAMENT CONTROL</span><h3>Tournament Center</h3><p class="muted">Create tournaments, run matchmaking and review results.</p></div><button class="small accent" onclick="openTournamentAdminCenter()">Open Tournament Admin →</button></div></section>\n  </div>`');
  return html;
};


/* ================= V6.1 OWNER TOURNAMENT ACCESS FIX =================
   The V6 tournament engine already existed, but the Squad Portal did not
   reliably expose a navigation entry to it. V6.1 adds a direct, role-gated
   Tournament Center button after the dashboard has rendered, avoiding the
   brittle HTML string replacement used in V6.
*/
const _v61BaseRender = render;
render = function(){
  _v61BaseRender();
  if(!current || !tournamentAdminAccess()) return;
  const sideNav=document.querySelector('.side-nav');
  if(!sideNav || sideNav.querySelector('[data-v61-tournament]')) return;
  const btn=document.createElement('button');
  btn.type='button';
  btn.className='side-link';
  btn.setAttribute('data-v61-tournament','true');
  btn.innerHTML='<span>🏆</span>Tournaments';
  btn.onclick=()=>openOwnerTournamentCenter();
  sideNav.appendChild(btn);
};

const _v61BaseOverview = overview;
overview = function(owner,leader){
  let html=_v61BaseOverview(owner,leader);
  if(tournamentAdminAccess()){
    const card=`<section class="panel v61-tournament-access" style="margin-top:18px"><div class="section-head"><div><span class="eyebrow">OWNER CONTROL</span><h3>Tournament Center</h3><p class="muted">Create tournaments, manage registrations, generate brackets, review results and control delegated Tournament Managers.</p></div><button class="small accent" onclick="openOwnerTournamentCenter()">Open Tournament Center →</button></div><div class="tour-login-note" style="margin-top:12px"><b>${ownerTournamentAccess()?'Dark System Owner':'Tournament Manager'}</b> — ${ownerTournamentAccess()?'You have full tournament authority.':'You have delegated tournament administration access.'}</div></section>`;
    const end=html.lastIndexOf('</div>');
    if(end!==-1) html=html.slice(0,end)+card+html.slice(end);
  }
  return html;
};

function notificationBarHtml(){
  const notes=(communityDb.notifications||[]).filter(n=>!n.audienceId || (communityCurrent&&String(n.audienceId)===String(communityCurrent.id))).slice(0,20);
  return `<div id="notificationBar" class="notification-bar ${notes.length?'':'empty'}"><div class="notification-bar-head"><div><span class="eyebrow">DARK SYSTEM</span><h3>Notifications</h3></div><button class="ghost small" onclick="markNotificationsRead();toggleNotificationBar()">Mark all read</button></div>${notes.map(n=>`<article class="notification-item ${n.read?'read':''}"><div class="notification-dot">${n.type==='cancelled'?'×':n.type==='removed'?'−':n.type==='reinstated'?'↺':'•'}</div><div><b>${esc(n.title)}</b><p>${esc(n.body)}</p><small>${fmt(n.time)}</small></div></article>`).join('')||'<p class="muted">No notifications yet.</p>'}</div>`;
}
function toggleNotificationBar(){const host=document.querySelector('.tournament-shell')||document.querySelector('.community-dashboard');if(!host)return;let bar=document.getElementById('notificationBar');if(bar){bar.remove();return;}host.insertAdjacentHTML('afterbegin',notificationBarHtml());}
async function markNotificationsRead(){if(DARK_BACKEND){try{await api('/api/community/notifications/read-all',{method:'POST'});await backendHydrate();}catch(err){return error('NOTIFICATIONS FAILED',err.message)}}else{(communityDb.notifications||[]).forEach(n=>{if(!n.audienceId || (communityCurrent&&String(n.audienceId)===String(communityCurrent.id)))n.read=true;});saveCommunity();}toggleNotificationBar();}

// Explicit window bindings make modal actions reliable in all browsers/webviews.
window.closeModal=()=>close();
window.openTournamentMatches=()=>{close();tourSetView('matches');};


/* ================= V6.4: TOURNAMENT HISTORY + CANCEL CONTROL + SESSION LOCK ================= */
function tournamentHistory(){
  const history=communityDb.tournaments
    .filter(t=>t.completed || String(t.status||'').toLowerCase()==='completed')
    .slice()
    .sort((a,b)=>new Date(b.completedAt||b.date||0)-new Date(a.completedAt||a.date||0));
  return `<section class="tour-admin-card manager-card" style="margin-top:18px">
    <div class="section-head"><div><span class="eyebrow">DARK SYSTEM HISTORY</span><h3>Tournament History</h3><p class="muted">Completed tournaments automatically leave Manage Existing and are permanently recorded here with their completion date and time.</p></div><span class="tour-chip">${history.length} completed</span></div>
    <div class="tour-list">${history.map(t=>{
      const champ=communityDb.accounts.find(a=>String(a.id)===String(t.champion));
      const runner=communityDb.accounts.find(a=>String(a.id)===String(t.runnerUp));
      return `<div class="tour-list-row history-row"><div><b>${esc(t.title)}</b><div class="meta">${esc(t.format||'MLBB')} • Tournament date: ${esc(t.date||'TBA')} • Completed: ${esc(fmt(t.completedAt))}</div><div class="meta">Champion: ${esc(champ?.ign||t.champion||'Not recorded')}${runner?' • Runner-up: '+esc(runner.ign):''}</div></div><span class="tour-chip">Completed</span></div>`;
    }).join('')||'<p class="muted">No completed tournaments have been recorded yet.</p>'}</div>
  </section>`;
}

function tourManagerDeniedForST(){return `<section class="tour-admin-card"><span class="eyebrow">ST APPROVAL</span><h2>Squad Tournament Approval</h2><p class="muted">Only the Squad Owner and authorized Tournament Managers can review Squad-vs-Squad registration requests.</p></section>`;}
function stApprovalView(){
  ensureTournamentSchema();
  const approvals=communityDb.squadTournamentApprovals||[];
  const pending=approvals.filter(a=>(a.status||'Pending')==='Pending');
  const recent=approvals.filter(a=>(a.status||'Pending')!=='Pending').slice().sort((a,b)=>new Date(b.updatedAt||b.createdAt||0)-new Date(a.updatedAt||a.createdAt||0)).slice(0,12);
  const row=a=>{const status=a.status||'Pending';const t=communityDb.tournaments.find(x=>String(x.id)===String(a.tournamentId));return `<div class="tour-list-row st-approval-row"><div><b>${esc(a.squadName||'Unnamed Squad')}</b><div class="meta">Leader: ${esc(a.leaderIgn||a.leaderName||'Unknown')} • Squad ID: ${esc(a.squadId||'—')} • ${esc(t?.title||a.tournamentTitle||'Squad Tournament')}</div><div class="meta">Submitted ${a.createdAt?esc(new Date(a.createdAt).toLocaleString()):'—'}</div></div><div class="tour-actions"><span class="tour-chip st-status-${status.toLowerCase()}">${esc(status)}</span>${status==='Pending'?`<button class="small accent" onclick="approveSTRequest('${a.id}')">Approve</button><button class="small danger" onclick="rejectSTRequest('${a.id}')">Reject</button>`:''}</div></div>`};
  return `<section class="tour-admin-card st-approval-page"><div class="section-head"><div><span class="eyebrow">SQUAD TOURNAMENT</span><h2>ST Approval</h2><p class="muted">Review invited Squad Leader registration requests. Approval reserves a squad slot and triggers a unique member registration code for the approved leader.</p></div><div class="tour-stat-card st-approval-count"><small>Pending Requests</small><b>${pending.length}</b></div></div><section class="st-approval-block"><div class="section-head"><div><h3>Pending Requests</h3><p class="muted">Approve only the leaders and squad details you have authorized for this tournament.</p></div></div><div class="tour-list">${pending.map(row).join('')||'<div class="tour-empty">No pending Squad Tournament approvals.</div>'}</div></section><section class="st-approval-block"><div class="section-head"><div><h3>Recent Decisions</h3><p class="muted">Approved and rejected requests remain visible here for reference.</p></div></div><div class="tour-list">${recent.map(row).join('')||'<div class="tour-empty">No approval history yet.</div>'}</div></section></section>`;
}
function approveSTRequest(id){
  if(!tournamentAdminAccess()) return error('ACCESS DENIED','You do not have Tournament Manager permission.');
  ensureTournamentSchema(); const a=communityDb.squadTournamentApprovals.find(x=>String(x.id)===String(id)); if(!a)return error('REQUEST NOT FOUND','This Squad Tournament request could not be found.');
  if((a.status||'Pending')!=='Pending')return error('ALREADY DECIDED','This request has already been processed.');
  const t=communityDb.tournaments.find(x=>String(x.id)===String(a.tournamentId));
  const approvedCount=communityDb.squadTournamentApprovals.filter(x=>String(x.tournamentId)===String(a.tournamentId)&&x.status==='Approved').length;
  const maxSquads=Number(a.maxSquads||t?.squadSlots||0);
  if(maxSquads && approvedCount>=maxSquads)return error('SQUAD SLOTS FULL','All configured squad slots for this tournament have already been approved.');
  a.status='Approved'; a.updatedAt=new Date().toISOString(); a.approvedBy=current?.id||null; a.memberAccessCode=a.memberAccessCode||`ST-${Math.random().toString(36).slice(2,7).toUpperCase()}-${Math.random().toString(36).slice(2,6).toUpperCase()}`;
  if(t){t.approvedSquadCount=(Number(t.approvedSquadCount)||0)+1; if(maxSquads && t.approvedSquadCount>=maxSquads){t.squadRegistrationOpen=false;}}
  addCommunityNotification('squad_approval','Squad Tournament Approved',`Your squad registration for ${t?.title||a.tournamentTitle||'the Squad Tournament'} was approved. Your member access code is ${a.memberAccessCode}.`,a.leaderAccountId||a.accountId||null);
  saveCommunity(); renderTournamentPage();
}
function rejectSTRequest(id){
  if(!tournamentAdminAccess()) return error('ACCESS DENIED','You do not have Tournament Manager permission.');
  ensureTournamentSchema(); const a=communityDb.squadTournamentApprovals.find(x=>String(x.id)===String(id)); if(!a)return error('REQUEST NOT FOUND','This Squad Tournament request could not be found.');
  if((a.status||'Pending')!=='Pending')return error('ALREADY DECIDED','This request has already been processed.');
  a.status='Rejected'; a.updatedAt=new Date().toISOString(); a.rejectedBy=current?.id||null;
  const t=communityDb.tournaments.find(x=>String(x.id)===String(a.tournamentId));
  addCommunityNotification('squad_approval_rejected','Squad Tournament Registration Update',`Your squad registration request for ${t?.title||a.tournamentTitle||'the Squad Tournament'} was not approved.`,a.leaderAccountId||a.accountId||null);
  saveCommunity(); renderTournamentPage();
}

function viewRegisteredParticipant(tournamentId, registrationId){
  if(!tournamentAdminAccess()) return error('ACCESS DENIED','Only Tournament Admins can view registered participant profiles.');
  const t=communityDb.tournaments.find(x=>String(x.id)===String(tournamentId));
  const r=communityDb.registrations.find(x=>String(x.id)===String(registrationId)&&String(x.tournamentId)===String(tournamentId));
  if(!t||!r) return error('REGISTRATION NOT FOUND','This registration could not be found.');
  const a=communityDb.accounts.find(x=>String(x.id)===String(r.accountId));
  const ign=a?.ign||r.ign||'Unknown Player';
  const gameId=a?.gameId||r.gameId||'—';
  const serverId=a?.serverId||r.serverId||'—';
  const role=a?.role||'Community Member';
  const squadName=a?.squadName||a?.squad||'—';
  const registeredAt=r.registeredAt?new Date(r.registeredAt).toLocaleString():'—';
  show(`<div class="login-wrap registered-profile-modal"><span class="eyebrow">REGISTERED PARTICIPANT</span><h2>${esc(ign)}</h2><p class="muted">Tournament profile • ${esc(t.title)}</p><div class="profile-data"><div><small>IGN</small><b>${esc(ign)}</b></div><div><small>GAME ID</small><b>${esc(gameId)}</b></div><div><small>SERVER ID</small><b>${esc(serverId)}</b></div><div><small>SQUAD</small><b>${esc(squadName)}</b></div><div><small>ROLE</small><b>${esc(role)}</b></div><div><small>REGISTRATION STATUS</small><b>${esc(r.status||'Registered')}</b></div><div><small>REGISTERED</small><b>${esc(registeredAt)}</b></div></div><div class="notice" style="margin-top:16px"><b>View-only profile</b><br><span>Tournament Admin can review this participant's tournament information, but cannot edit their personal profile.</span></div><div class="actions"><button type="button" class="primary" onclick="close();v64ManageTournament('${t.id}')">Back to Registrations</button><button type="button" class="ghost" onclick="close()">Close</button></div></div>`);
}

function v64ManageTournament(id){
  if(!tournamentAdminAccess()) return error('ACCESS DENIED','You do not have Tournament Manager permission.');
  const t=communityDb.tournaments.find(x=>String(x.id)===String(id));
  if(!t)return error('TOURNAMENT NOT FOUND','This tournament could not be found.');
  if(t.completed || String(t.status||'').toLowerCase()==='completed') return error('TOURNAMENT COMPLETED','This tournament has moved to Tournament History.');
  const regs=communityDb.registrations.filter(r=>String(r.tournamentId)===String(id));
  const matched=!!t.bracketReady;
  const cancelButton=ownerTournamentAccess() && t.status!=='Cancelled'
    ? `<button type="button" class="danger" id="manageCancelTournament">Cancel Tournament</button>` : '';
  const reinstateButton=ownerTournamentAccess() && t.status==='Cancelled' && cancelledRemainingMs(t)>0
    ? `<button type="button" class="small accent" id="manageReinstateTournament">Reinstate (${cancelledRemainingText(t)})</button>` : '';
  show(`<div class="login-wrap"><span class="eyebrow">TOURNAMENT ADMIN</span><h2>${esc(t.title)}</h2><p class="muted">${regs.length}${t.slots?` / ${esc(t.slots)}`:''} registered • ${esc(t.format||'MLBB')} • Status: <b>${esc(t.status||'Open')}</b></p>
    <div class="tour-list">${regs.map((r,i)=>{const a=communityDb.accounts.find(x=>String(x.id)===String(r.accountId));const ign=a?.ign||r.ign||'Unknown Player';const gameId=a?.gameId||r.gameId||'—';const serverId=a?.serverId||r.serverId||'—';return `<div class="tour-list-row registered-participant-row" role="button" tabindex="0" onclick="viewRegisteredParticipant('${t.id}','${r.id}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();viewRegisteredParticipant('${t.id}','${r.id}')}" title="View registered profile"><div><b>${i+1}. ${esc(ign)}</b><div class="meta">ID ${esc(gameId)} • Server ${esc(serverId)}</div></div><div class="tour-actions"><span class="tour-chip">${esc(r.status||'Registered')}</span><button type="button" class="small accent" onclick="event.stopPropagation();viewRegisteredParticipant('${t.id}','${r.id}')">View Profile</button></div></div>`}).join('')||'<p class="muted">No registrations yet.</p>'}</div>
    <div class="actions"><button class="primary" id="manualMatchBtn" ${regs.length<2||matched||t.status==='Cancelled'?'disabled':''}>${matched?'Matchmaking Complete':'Run Matchmaking Now'}</button>${cancelButton}${reinstateButton}<button class="ghost" id="closeManageBtn">Close</button></div>
    <p class="muted" style="margin-top:12px">${t.status==='Cancelled'?'This tournament is cancelled and registration is closed.':matched?'Registration is closed and matches have been generated.':'Players will be matched automatically when the tournament reaches its configured capacity.'}</p></div>`);
  document.getElementById('closeManageBtn')?.addEventListener('click',close);
  document.getElementById('manageCancelTournament')?.addEventListener('click',()=>cancelTournamentConfirm(id));
  document.getElementById('manageReinstateTournament')?.addEventListener('click',()=>reinstateTournament(id));
  document.getElementById('manualMatchBtn')?.addEventListener('click',()=>{
    if(!tournamentAdminAccess()) return error('ACCESS DENIED','You do not have Tournament Manager permission.');
    const ok=autoMatchmakeIfReady(t);
    if(!ok) return error('NOT READY','Automatic matchmaking requires the tournament to reach its configured capacity and a valid team size.');
    close(); renderTournamentPage();
    show(`<div class="setup-lock"><div class="setup-icon">✓</div><span class="eyebrow">MATCHMAKING COMPLETE</span><h2>${esc(t.title)}</h2><p class="muted">Registration is closed and the matches have been generated automatically.</p><div class="actions"><button type="button" class="primary" id="openMatchesBtn">Open Matches</button></div></div>`);
    document.getElementById('openMatchesBtn')?.addEventListener('click',()=>{close();tourSetView('matches')});
  });
}
tourManage=v64ManageTournament;

function tourManagement(){
  if(!ownerTournamentAccess()) return tourManagementDenied();
  const candidates=db.members.filter(m=>['Squad Leader','Assistant Squad Leader'].includes(m.role));
  communityDb.tournamentManagers=communityDb.tournamentManagers||[];
  const rows=candidates.map(m=>{const active=communityDb.tournamentManagers.some(id=>String(id)===String(m.id));return `<div class="tour-list-row"><div><b>${esc(m.name||m.ign)}</b><div class="meta">${esc(m.ign)} • ${esc(m.role)} • ${active?'Tournament Management: Granted':'Tournament Management: Not granted'}</div></div><div class="tour-actions">${active?`<button class="small danger" onclick="revokeTournamentManager('${m.id}');return false;">Revoke Access</button>`:`<button class="small accent" onclick="grantTournamentManager('${m.id}');return false;">Grant Access</button>`}</div></div>`}).join('');
  return `<section class="tour-admin-card"><span class="eyebrow">SQUAD OWNER</span><h2>Tournament Management</h2><p class="muted">Grant or revoke tournament-management access for individual Squad Leaders. Squad Leader rank and Tournament Management permission are separate.</p><div class="notice"><b>Recommended permission model</b><br><span>Only grant Tournament Management to leaders who need to create/manage tournaments, run matchmaking and review results. A Squad Leader does not automatically receive tournament-management access.</span></div><div class="tour-list" style="margin-top:18px">${rows||'<p class="muted">No Squad Leaders are currently eligible for Tournament Management.</p>'}</div></section>`;
}
function tourManagementDenied(){return `<section class="tour-admin-card"><span class="eyebrow">OWNER ONLY</span><h2>Tournament Management</h2><p class="muted">Only the Squad Owner can grant or revoke Tournament Management access.</p></section>`;}

function v64TourAdmin(){
  if(isTournamentManager() && !ownerTournamentAccess()) return tourManagerAdminV64();
  const pending=[];
  communityDb.tournaments.forEach(t=>(t.matches||[]).forEach(m=>{
    if(m.submission&&['Awaiting Confirmation','Disputed'].includes(m.submission.status)) pending.push({t,m});
  }));
  const active=communityDb.tournaments.filter(t=>!t.completed && String(t.status||'').toLowerCase()!=='completed');
  return `<div class="tour-stat-row"><div class="tour-stat-card"><small>ACTIVE TOURNAMENTS</small><b>${active.length}</b></div><div class="tour-stat-card"><small>REGISTRATIONS</small><b>${communityDb.registrations.length}</b></div><div class="tour-stat-card"><small>PENDING REVIEWS</small><b>${pending.length}</b></div><div class="tour-stat-card"><small>HISTORY</small><b>${communityDb.tournaments.filter(t=>t.completed).length}</b></div></div>
    <div class="admin-grid">
      <section class="tour-admin-card"><span class="eyebrow">OWNER CONTROL</span><h3>Create Tournament</h3><form id="createTourForm" class="tour-form"><label>Title<input id="ntTitle" required placeholder="Dark System 1v1 Championship"></label><label>Format<select id="ntFormat"><option>1v1</option><option>5v5</option><option>2v2</option></select></label><label>Game<input value="Mobile Legends: Bang Bang" disabled></label><label>Date<input id="ntDate" type="date" required></label><label>Start Time<input id="ntTime" type="time" required></label><label>Registration Deadline<input id="ntDeadline" type="date"></label><label>Slots<input id="ntSlots" type="number" min="2" value="32" required></label><label>Prize / Reward<input id="ntReward" placeholder="₦10,000"></label><label class="full">Rules<textarea id="ntRules" required placeholder="Enter the tournament rules..."></textarea></label><label class="full">Description<textarea id="ntDesc" placeholder="Tournament description..."></textarea></label><div class="actions full"><button class="primary">Publish Tournament</button></div></form></section>
      <section class="tour-admin-card"><span class="eyebrow">TOURNAMENTS</span><h3>Manage Existing</h3><div class="tour-list">${active.map(t=>`<div class="tour-list-row"><div><b>${esc(t.title)}</b><div class="meta">${esc(t.format||'MLBB')} • ${esc(t.status||'Open')} • ${communityDb.registrations.filter(r=>String(r.tournamentId)===String(t.id)).length} registered</div></div><div class="tour-actions"><button class="small accent" onclick="tourManage('${t.id}')">Manage</button></div></div>`).join('')||'<p class="muted">No active tournaments. Completed tournaments appear in Tournament History.</p>'}</div></section>
    </div>
    ${tournamentHistory()}
    <section class="tour-admin-card" style="margin-top:18px"><span class="eyebrow">RESULT REVIEW</span><h3>Pending Match Results</h3>${pending.map(x=>`<div class="tour-list-row"><div><b>${esc(x.t.title)} • Match #${esc(x.m.number)}</b><div class="meta">${esc(x.m.submission.submitterResult||'Result')} • Winner submitted: ${esc(communityDb.accounts.find(a=>a.id===x.m.submission.winner)?.ign||'Unknown')} • ${esc(x.m.submission.status)} • Battle ID: ${esc(x.m.submission.battleId||'Not provided')}</div></div><div class="tour-actions"><button class="small accent" onclick="ownerApproveResult('${x.t.id}','${x.m.id}')">Approve</button><button class="small danger" onclick="ownerRejectResult('${x.t.id}','${x.m.id}')">Reject</button></div></div>`).join('')||'<p class="muted">No pending results.</p>'}</section>`;
}

tourManagerAdminV64=function(){
  const pending=[];
  communityDb.tournaments.forEach(t=>(t.matches||[]).forEach(m=>{
    if(m.submission&&['Awaiting Confirmation','Disputed'].includes(m.submission.status)) pending.push({t,m});
  }));
  const active=communityDb.tournaments.filter(t=>!t.completed && String(t.status||'').toLowerCase()!=='completed');
  return `<div class="tour-manager-shell">
    <section class="tour-manager-hero"><div><span class="eyebrow">DELEGATED ACCESS</span><h2>Tournament Manager Portal</h2><p class="muted">You have tournament-management permissions only. This is not the Squad Owner interface.</p></div><div class="tour-manager-badge">TOURNAMENT MANAGER</div></section>
    <div class="tour-stat-row"><div class="tour-stat-card"><small>ACTIVE</small><b>${active.length}</b></div><div class="tour-stat-card"><small>REGISTRATIONS</small><b>${communityDb.registrations.length}</b></div><div class="tour-stat-card"><small>PENDING REVIEWS</small><b>${pending.length}</b></div><div class="tour-stat-card"><small>HISTORY</small><b>${communityDb.tournaments.filter(t=>t.completed).length}</b></div></div>
    <div class="admin-grid"><section class="tour-admin-card manager-card"><span class="eyebrow">TOURNAMENT MANAGER</span><h3>Create Tournament</h3><form id="createTourForm" class="tour-form"><label>Title<input id="ntTitle" required placeholder="Dark System 1v1 Championship"></label><label>Format<select id="ntFormat"><option>1v1</option><option>5v5</option><option>2v2</option></select></label><label>Game<input value="Mobile Legends: Bang Bang" disabled></label><label>Date<input id="ntDate" type="date" required></label><label>Start Time<input id="ntTime" type="time" required></label><label>Registration Deadline<input id="ntDeadline" type="date"></label><label>Slots<input id="ntSlots" type="number" min="2" value="32" required></label><label>Prize / Reward<input id="ntReward" placeholder="Tournament Rewards"></label><label class="full">Rules<textarea id="ntRules" required placeholder="Enter the tournament rules..."></textarea></label><label class="full">Description<textarea id="ntDesc" placeholder="Tournament description..."></textarea></label><div class="actions full"><button class="primary">Publish Tournament</button></div></form></section>
      <section class="tour-admin-card manager-card"><span class="eyebrow">MANAGE TOURNAMENTS</span><h3>Manage Existing</h3><div class="tour-list">${active.map(t=>`<div class="tour-list-row"><div><b>${esc(t.title)}</b><div class="meta">${esc(t.format||'MLBB')} • ${esc(t.status||'Open')} • ${communityDb.registrations.filter(r=>String(r.tournamentId)===String(t.id)).length} registered</div></div><div class="tour-actions"><button class="small accent" onclick="tourManage('${t.id}')">Manage</button></div></div>`).join('')||'<p class="muted">No active tournaments. Completed tournaments appear in Tournament History.</p>'}</div></section></div>
    ${tournamentHistory()}
    <section class="tour-admin-card manager-card" style="margin-top:18px"><span class="eyebrow">RESULT REVIEW</span><h3>Pending Match Results</h3>${pending.map(x=>`<div class="tour-list-row"><div><b>${esc(x.t.title)} • Match #${esc(x.m.number)}</b><div class="meta">${esc(x.m.submission.submitterResult||'Result')} • Winner submitted: ${esc(communityDb.accounts.find(a=>a.id===x.m.submission.winner)?.ign||'Unknown')} • ${esc(x.m.submission.status)} • Battle ID: ${esc(x.m.submission.battleId||'Not provided')}</div></div><div class="tour-actions"><button class="small accent" onclick="ownerApproveResult('${x.t.id}','${x.m.id}')">Approve</button><button class="small danger" onclick="ownerRejectResult('${x.t.id}','${x.m.id}')">Reject</button></div></div>`).join('')||'<p class="muted">No pending results.</p>'}</section>
    <section class="tour-manager-permissions"><b>Access boundary</b><p>You can manage tournaments and match results. Squad ownership, squad permissions and Tournament Manager grants remain unavailable to you.</p></section></div>`;
};

tourAdmin=v64TourAdmin;

// Prevent the navigation itself from pretending another portal can be opened while a session is active.
function refreshPortalNavLock(){
  refreshSiteMenu();
  const squad=document.getElementById('loginBtn');
  const comm=document.getElementById('communityLoginBtn');
  if(squad){squad.title=communityCurrent?'Log out of Community before entering the Squad Portal.':'';}
  if(comm){comm.title=current?'Log out of the Squad Portal before entering Community.':communityCurrent?'Log out of Community before opening Community Login again.':'';}
}

const _v64BaseRenderTournamentPage=renderTournamentPage;
renderTournamentPage=function(){
  if(tournamentView==='history' && !tournamentAdminAccess()) tournamentView='overview';
  _v64BaseRenderTournamentPage();
  if(!tournamentAdminAccess()) return;
  const tabs=document.querySelector('.tour-tabs');
  if(tabs && !tabs.querySelector('[data-v64-history]')){
    const b=document.createElement('button');
    b.className='tour-tab'+(tournamentView==='history'?' active':'');
    b.setAttribute('data-v64-history','true');
    b.textContent='History';
    b.onclick=()=>tourSetView('history');
    tabs.appendChild(b);
  }
  if(tournamentView==='history'){
    const shell=document.querySelector('.tournament-shell');
    if(shell){
      const existing=shell.querySelector('.v64-history-page');
      if(existing) existing.remove();
      const page=document.createElement('div');
      page.className='v64-history-page';
      page.innerHTML=tournamentHistory();
      const footer=shell.querySelector('.tour-page-footer');
      shell.insertBefore(page,footer||null);
    }
  }
};

const _v64RenderCommunityApp=renderCommunityApp;
renderCommunityApp=function(){_v64RenderCommunityApp();refreshPortalNavLock();};
const _v64CommunityLogout=communityLogout;
communityLogout=function(){_v64CommunityLogout();refreshPortalNavLock();};
const _v64OpenApp=openApp;
openApp=function(){_v64OpenApp();refreshPortalNavLock();};
const _v64Logout=logout;
logout=function(){_v64Logout();refreshPortalNavLock();};
refreshPortalNavLock();

/* ================= V12: SQUAD-VS-SQUAD TOURNAMENT WORKFLOW ================= */
function ensureSquadTournamentFields(){
  communityDb.tournaments=(communityDb.tournaments||[]).map(t=>{
    if(t.format==='Squad vs Squad'){
      t.squadSlots=Number(t.squadSlots||t.slots||8);
      t.membersPerSquad=Number(t.membersPerSquad||7);
      t.leaderAccessCode=t.leaderAccessCode||generateTournamentCode('DS-ST');
      t.approvedSquadCount=Number(t.approvedSquadCount||0);
      t.squadRegistrationOpen=t.squadRegistrationOpen!==false;
      t.slots=t.squadSlots*t.membersPerSquad;
    }
    return t;
  });
  communityDb.squadTournamentApprovals=Array.isArray(communityDb.squadTournamentApprovals)?communityDb.squadTournamentApprovals:[];
  saveCommunity();
}
ensureSquadTournamentFields();

function squadCreateFormHTML(){
  return `<form id="createTourForm" class="tour-form">
    <label>Title<input id="ntTitle" required placeholder="Dark System Squad Championship"></label>
    <label>Format<select id="ntFormat"><option>1v1</option><option>5v5</option><option>2v2</option><option>Squad vs Squad</option></select></label>
    <label>Game<input value="Mobile Legends: Bang Bang" disabled></label>
    <label>Date<input id="ntDate" type="date" required></label>
    <label>Start Time<input id="ntTime" type="time" required></label>
    <label>Registration Deadline<input id="ntDeadline" type="date"></label>
    <label id="normalSlotsField">Slots<input id="ntSlots" type="number" min="2" value="32" required></label>
    <label id="squadSlotsField" class="hidden">Squad Slots<input id="ntSquadSlots" type="number" min="2" max="64" value="8"></label>
    <label id="membersPerSquadField" class="hidden">Maximum Members Per Squad<input id="ntMembersPerSquad" type="number" min="5" max="15" value="7"></label>
    <label>Prize / Reward<input id="ntReward" placeholder="Tournament Rewards"></label>
    <label class="full">Rules<textarea id="ntRules" required placeholder="Enter the tournament rules..."></textarea></label>
    <label class="full">Description<textarea id="ntDesc" placeholder="Tournament description..."></textarea></label>
    <div id="squadCreateInfo" class="notice full hidden"><b>Squad-vs-Squad setup</b><br><span>The system will generate one invitation code after publishing. Send that code only to the Squad Leaders you authorize. Leaders submit their squad name, Squad ID and locked Squad Leader role for approval. After approval, each squad receives its own member access code.</span></div>
    <div class="actions full"><button class="primary">Publish Tournament</button></div>
  </form>`;
}
function updateSquadCreateFields(){
  const format=document.getElementById('ntFormat')?.value;
  const squad=format==='Squad vs Squad';
  document.getElementById('normalSlotsField')?.classList.toggle('hidden',squad);
  document.getElementById('squadSlotsField')?.classList.toggle('hidden',!squad);
  document.getElementById('membersPerSquadField')?.classList.toggle('hidden',!squad);
  document.getElementById('squadCreateInfo')?.classList.toggle('hidden',!squad);
  const slots=document.getElementById('ntSlots'); if(slots) slots.required=!squad;
  const ss=document.getElementById('ntSquadSlots'); if(ss) ss.required=squad;
  const mp=document.getElementById('ntMembersPerSquad'); if(mp) mp.required=squad;
}
function renderV12CreateForm(html){
  return html.replace(/<form id="createTourForm" class="tour-form">[\s\S]*?<\/form>/,squadCreateFormHTML());
}
const _v12BaseTourAdmin=v64TourAdmin;
v64TourAdmin=function(){
  ensureSquadTournamentFields();
  let html=renderV12CreateForm(_v12BaseTourAdmin());
  return html;
};
tourAdmin=v64TourAdmin;

bindTournamentAdmin=function(){
  const f=document.getElementById('createTourForm'); if(!f)return;
  const fmt=document.getElementById('ntFormat');
  fmt?.addEventListener('change',updateSquadCreateFields);
  updateSquadCreateFields();
  f.onsubmit=async e=>{
    e.preventDefault();
    if(!tournamentAdminAccess())return error('ACCESS DENIED','You do not have Tournament Manager permission.');
    const format=fmt.value, title=ntTitle.value.trim(), date=ntDate.value, time=ntTime.value, deadline=ntDeadline.value;
    const reward=ntReward.value.trim()||'Tournament Rewards', rules=ntRules.value.trim(), desc=ntDesc.value.trim();
    if(format==='Squad vs Squad'){
      const squadSlots=Number(document.getElementById('ntSquadSlots').value||0), members=Number(document.getElementById('ntMembersPerSquad').value||0);
      if(squadSlots<2)return error('INVALID SQUAD SLOTS','Choose at least 2 squad slots.');
      if(members<5)return error('INVALID SQUAD SIZE','Each squad needs at least 5 members because the game is 5v5.');
      const t={id:'T'+Date.now(),title,game:'Mobile Legends: Bang Bang',format,date,time,registrationDeadline:deadline,slots:squadSlots*members,squadSlots,membersPerSquad:members,approvedSquadCount:0,squadRegistrationOpen:true,leaderAccessCode:generateTournamentCode('DS-ST'),status:'Open',registrationOpen:true,reward,rules,description:desc,matches:[],completed:false,champion:'',runnerUp:'',bracketReady:false,createdAt:new Date().toISOString()};
      if(DARK_BACKEND){const data=await api('/api/tournaments',{method:'POST',body:JSON.stringify(t)});if(data.tournament)t=data.tournament;}else communityDb.tournaments.push(t);
      addCommunityNotification('added','New Squad Tournament Added',`${t.title} is now open for authorized Squad Leader registration.`);
      saveCommunity(); f.reset();
      document.getElementById('ntSquadSlots').value='8'; document.getElementById('ntMembersPerSquad').value='7'; updateSquadCreateFields(); tourSetView('admin');
      show(`<div class="setup-lock"><div class="setup-icon">✓</div><span class="eyebrow">SQUAD TOURNAMENT CREATED</span><h2>${esc(t.title)}</h2><p class="muted">${esc(t.squadSlots)} squad slots • ${esc(t.membersPerSquad)} members per squad • 5 starters + ${esc(t.membersPerSquad-5)} substitutes.</p><div class="notice" style="margin-top:16px"><b>Initial Squad Leader Access Code</b><br><strong style="font-size:1.35rem;letter-spacing:.08em">${esc(t.leaderAccessCode)}</strong><br><button type="button" class="small accent" style="margin-top:10px" onclick="copyAccessCode('${esc(t.leaderAccessCode)}',this)">Copy Code</button><br><span>Send this one code only to the Squad Leaders you authorize. Their requests still require your approval in ST Approval.</span></div><div class="actions"><button class="primary" onclick="close();renderTournamentPage()">Done</button></div></div>`);
      return;
    }
    const slots=Number(ntSlots.value||0), groupSize=format==='1v1'?1:(format==='2v2'?2:5), minSlots=groupSize*2;
    if(slots<minSlots)return error('INVALID SLOT COUNT',`This ${format} tournament needs at least ${minSlots} player slots.`);
    if(slots%groupSize!==0)return error('INVALID SLOT COUNT',`For ${format}, total slots must be a multiple of ${groupSize}.`);
    if(format==='1v1'&&slots%2!==0)return error('INVALID SLOT COUNT','A 1v1 tournament needs an even number of player slots.');
    const t={id:'T'+Date.now(),title,game:'Mobile Legends: Bang Bang',format,date,time,registrationDeadline:deadline,slots,status:'Open',registrationOpen:true,reward,rules,description:desc,matches:[],completed:false,champion:'',runnerUp:'',bracketReady:false,createdAt:new Date().toISOString()};
    if(DARK_BACKEND){const data=await api('/api/tournaments',{method:'POST',body:JSON.stringify(t)});if(data.tournament)t=data.tournament;}else communityDb.tournaments.push(t);addCommunityNotification('added','New tournament added',`${t.title} is now open for registration.`);saveCommunity();f.reset();ntSlots.value=format==='1v1'?32:format==='2v2'?8:10;updateSquadCreateFields();tourSetView('admin');
  };
};

/* Add the invitation-code and squad-capacity details to tournament management. */
const _v12ManageTournament=v64ManageTournament;
v64ManageTournament=function(id){
  _v12ManageTournament(id);
  const t=communityDb.tournaments.find(x=>String(x.id)===String(id));
  if(t?.format!=='Squad vs Squad')return;
  const modal=document.querySelector('#modal .login-wrap'); if(!modal)return;
  const existing=modal.querySelector('.st-manage-summary'); if(existing)return;
  const regs=communityDb.registrations.filter(r=>String(r.tournamentId)===String(id));
  const squads=(communityDb.squadTournamentApprovals||[]).filter(a=>String(a.tournamentId)===String(id)&&a.status==='Approved');
  modal.insertAdjacentHTML('afterbegin',`<div class="notice st-manage-summary" style="margin:14px 0"><b>Squad-vs-Squad setup</b><br><span>${esc(t.squadSlots)} squad slots • ${esc(t.membersPerSquad)} members per squad • ${regs.length}/${esc(t.squadSlots*t.membersPerSquad)} total members registered • ${squads.length}/${esc(t.squadSlots)} squads approved.</span><br><span>Leader invitation code: <strong>${esc(t.leaderAccessCode)}</strong></span></div>`);
};

/* Keep tournament registration identity synchronized with the current Community profile. */
function syncTournamentRegistrationProfiles(){
  (communityDb.registrations||[]).forEach(r=>{
    const a=communityDb.accounts.find(x=>String(x.id)===String(r.accountId));
    if(a){r.ign=a.ign||r.ign;r.gameId=a.gameId||r.gameId;r.serverId=a.serverId||r.serverId;r.squadRole=a.role||r.squadRole||'Squad Member';}
  });
  (communityDb.squadTournamentApprovals||[]).forEach(a=>{
    const acc=communityDb.accounts.find(x=>String(x.id)===String(a.leaderAccountId));
    if(acc){a.leaderIgn=acc.ign||a.leaderIgn;a.leaderGameId=acc.gameId||a.leaderGameId;a.leaderServerId=acc.serverId||a.leaderServerId;}
  });
  saveCommunity();
}
const _v12RenderTournamentPage=renderTournamentPage;
renderTournamentPage=function(){ensureSquadTournamentFields();syncTournamentRegistrationProfiles();_v12RenderTournamentPage();};
tourManage=v64ManageTournament;

function enforceTournamentRegistrationDeadlines(){
  const now=Date.now();
  (communityDb.tournaments||[]).forEach(t=>{
    if(!t.registrationDeadline||t.registrationOpen===false||String(t.status||'').toLowerCase()!=='open')return;
    const end=new Date(`${t.registrationDeadline}T23:59:59`).getTime();
    if(!Number.isNaN(end)&&now>end){
      t.registrationOpen=false;
      if(t.format==='Squad vs Squad')t.squadRegistrationOpen=false;
    }
  });
  saveCommunity();
}
const _v12EnsureSquadFields=ensureSquadTournamentFields;
ensureSquadTournamentFields=function(){_v12EnsureSquadFields();enforceTournamentRegistrationDeadlines();};

/* ================= V13 FIX: CLEAN SQUAD-VS-SQUAD WORKFLOW ================= */
function stRegistrationDeadlineMs(t){
  if(!t?.registrationDeadline) return Infinity;
  const ms=new Date(`${t.registrationDeadline}T23:59:59`).getTime();
  return Number.isNaN(ms)?Infinity:ms;
}
function stLeaderCodeValid(t){
  if(!t || t.format!=='Squad vs Squad' || !t.leaderAccessCode) return false;
  if(t.registrationOpen===false || t.squadRegistrationOpen===false) return false;
  if(Date.now()>stRegistrationDeadlineMs(t)) return false;
  const approved=(communityDb.squadTournamentApprovals||[]).filter(a=>String(a.tournamentId)===String(t.id)&&a.status==='Approved').length;
  return approved < Number(t.squadSlots||0);
}
function stMemberCodeValid(t,a){
  if(!t || t.format!=='Squad vs Squad' || !a || a.status!=='Approved' || !a.memberAccessCode) return false;
  if(t.registrationOpen===false) return false;
  if(Date.now()>stRegistrationDeadlineMs(t)) return false;
  const count=communityDb.registrations.filter(r=>String(r.tournamentId)===String(t.id)&&String(r.squadApprovalId)===String(a.id)).length;
  return count < Number(t.membersPerSquad||a.membersPerSquad||7);
}
function stNotifyOwner(title,body){
  const owner=db.members.find(m=>m.role==='Squad Owner');
  if(owner){const acc=ensureLinkedCommunityAccount(owner); if(acc)addCommunityNotification('squad_tournament_admin',title,body,String(acc.id));}
}
function ensureV13SquadTournamentData(){
  communityDb.tournaments=(communityDb.tournaments||[]).map(t=>{
    // Migrate the built-in Squad-vs-Squad demo tournament if an older version stored it as 5v5.
    if(t.id==='T2' && /squad\s*vs\s*squad/i.test(t.title||'')) t.format='Squad vs Squad';
    if(t.format==='Squad vs Squad'){
      t.squadSlots=Number(t.squadSlots||8);
      t.membersPerSquad=Number(t.membersPerSquad||7);
      t.slots=t.squadSlots*t.membersPerSquad;
      t.approvedSquadCount=Number(t.approvedSquadCount||0);
      t.squadRegistrationOpen=t.squadRegistrationOpen!==false;
      t.registrationOpen=t.registrationOpen!==false;
      t.leaderAccessCode=t.leaderAccessCode||generateTournamentCode('DS-ST');
      t.leaderAccessCodeCreatedAt=t.leaderAccessCodeCreatedAt||t.createdAt||new Date().toISOString();
    }
    return t;
  });
  communityDb.squadTournamentApprovals=Array.isArray(communityDb.squadTournamentApprovals)?communityDb.squadTournamentApprovals:[];
  communityDb.squadTournamentApprovals.forEach(a=>{
    a.status=a.status||'Pending';
    a.membersPerSquad=Number(a.membersPerSquad||7);
    a.maxSquads=Number(a.maxSquads||0);
  });
  saveCommunity();
}
ensureV13SquadTournamentData();

// Replace the older generic registration handler so Squad-vs-Squad can never fall through into 1v1/5v5 registration.
registerFromTournament=function(id){
  const t=communityDb.tournaments.find(x=>String(x.id)===String(id));
  if(!t || String(t.status||'').toLowerCase()!=='open' || t.registrationOpen===false) return error('REGISTRATION CLOSED','This tournament is not open for registration.');
  if(t.format==='Squad vs Squad'){
    if(!communityCurrent){pendingTournamentId=id;communityAuth();return;}
    const already=communityDb.registrations.some(r=>String(r.accountId)===String(communityCurrent.id)&&String(r.tournamentId)===String(id));
    if(already)return error('ALREADY REGISTERED','Your profile is already registered for this tournament.');
    return squadTournamentRegistration(t);
  }
  if(!communityCurrent){pendingTournamentId=id;communityAuth();return;}
  if(communityDb.registrations.some(r=>String(r.accountId)===String(communityCurrent.id)&&String(r.tournamentId)===String(id)))return error('ALREADY REGISTERED','You are already registered for this tournament.');
  const count=communityDb.registrations.filter(r=>String(r.tournamentId)===String(id)).length;
  if(Number(t.slots)&&count>=Number(t.slots))return error('TOURNAMENT FULL','All available registration slots have been filled.');
  show(`<div class="login-wrap"><span class="eyebrow">CONFIRM REGISTRATION</span><h2>Register for ${esc(t.title)}</h2><p class="muted">Your saved Community profile will be used for this registration.</p>${registrationPreview(t)}<div class="profile-data"><div><small>FORMAT</small><b>${esc(t.format)}</b></div><div><small>DATE</small><b>${esc(t.date||'TBA')}</b></div><div><small>START</small><b>${esc(t.time||'TBA')}</b></div></div><div class="actions"><button class="primary" id="confirmTournamentRegistration">Confirm Registration</button><button class="ghost" onclick="close()">Cancel</button></div></div>`);
  document.getElementById('confirmTournamentRegistration')?.addEventListener('click',()=>completeTournamentRegistration(t.id));
};

// Clean Squad-vs-Squad leader/member registration UI and rules.
squadTournamentRegistration=function(t){
  if(!communityCurrent)return communityAuth();
  ensureV13SquadTournamentData();
  const leaderOpen=stLeaderCodeValid(t);
  const memberOpen=String(t.status||'').toLowerCase()==='open' && t.registrationOpen!==false;
  show(`<div class="login-wrap squad-st-registration"><span class="eyebrow">SQUAD-VS-SQUAD</span><h2>Register for ${esc(t.title)}</h2><p class="muted">Your Community profile is already recognized. Choose how you are joining this Squad-vs-Squad tournament.</p><div class="st-registration-choice-grid"><button type="button" class="choice-card" id="stRegisterSquadChoice" ${leaderOpen?'':'disabled'}><b>Register a Squad</b><small>For the Squad Leader who received the initial tournament access code from the Tournament Admin.</small></button><button type="button" class="choice-card" id="stJoinSquadChoice" ${memberOpen?'':'disabled'}><b>Join a Squad</b><small>For a squad member using the unique member access code sent by their Squad Leader.</small></button></div><div class="actions"><button type="button" class="ghost" onclick="close()">Cancel</button></div></div>`);
  document.getElementById('stRegisterSquadChoice')?.addEventListener('click',()=>showSTLeaderForm(t));
  document.getElementById('stJoinSquadChoice')?.addEventListener('click',()=>showSTMemberForm(t));
};
function showSTLeaderForm(t){
  if(!stLeaderCodeValid(t))return error('SQUAD REGISTRATION CLOSED','The initial Squad Leader access code is no longer valid because squad registration is closed.');
  show(`<div class="login-wrap squad-st-registration"><span class="eyebrow">SQUAD-VS-SQUAD</span><h2>Register Your Squad</h2><p class="muted">Your Community profile is already recognized. You are registering an external or Dark System squad for this tournament.</p><form id="stLeaderForm" class="form"><label>Community Profile<input value="${esc(communityCurrent.ign)} • ${esc(communityCurrent.gameId)} / ${esc(communityCurrent.serverId)}" disabled></label><label>In-Game Squad Name<input id="stSquadName" required placeholder="Exact MLBB squad name"></label><label>Squad ID<input id="stSquadId" required placeholder="Exact MLBB squad ID"></label><label>Squad Role<input value="Squad Leader" disabled></label><label>Tournament Access Code<input id="stLeaderCode" required placeholder="Enter the code sent to you"></label><div class="notice"><b>Important</b><br><span>The squad does not need to exist in the Dark System Squad Portal. The Squad Name and Squad ID must exactly match Mobile Legends. The role is fixed as Squad Leader.</span></div><div class="actions"><button class="primary">Submit for ST Approval</button><button type="button" class="ghost" onclick="squadTournamentRegistration(communityDb.tournaments.find(x=>String(x.id)===String('${t.id}')))" >Back</button></div></form></div>`);
  document.getElementById('stLeaderForm').onsubmit=e=>{e.preventDefault();submitSTLeaderRegistration(t.id,document.getElementById('stSquadName').value.trim(),document.getElementById('stSquadId').value.trim(),document.getElementById('stLeaderCode').value.trim(),communityCurrent,null);};
}
function showSTMemberForm(t){
  show(`<div class="login-wrap squad-st-registration"><span class="eyebrow">SQUAD-VS-SQUAD</span><h2>Join Your Squad</h2><p class="muted">Your Community profile is already recognized. Enter the unique code sent to you by the approved Squad Leader.</p><form id="stMemberForm" class="form"><label>Community Profile<input value="${esc(communityCurrent.ign)} • ${esc(communityCurrent.gameId)} / ${esc(communityCurrent.serverId)}" disabled></label><label>Squad Member Access Code<input id="stMemberCode" required placeholder="Enter your unique squad code"></label><div class="notice"><b>Automatic squad linking</b><br><span>The code identifies the approved squad automatically. You do not need to enter a squad name, Squad ID or Squad Portal details.</span><br><span>Maximum ${esc(t.membersPerSquad||7)} registered members per squad: 5 starters and ${esc(Math.max(0,(t.membersPerSquad||7)-5))} substitutes.</span></div><div class="actions"><button class="primary">Register to Squad</button><button type="button" class="ghost" onclick="squadTournamentRegistration(communityDb.tournaments.find(x=>String(x.id)===String('${t.id}')))" >Back</button></div></form></div>`);
  document.getElementById('stMemberForm').onsubmit=e=>{e.preventDefault();submitSTMemberRegistration(t.id,document.getElementById('stMemberCode').value.trim(),communityCurrent);};
}

submitSTLeaderRegistration=function(tid,squadName,squadId,code,account,member){
  const t=communityDb.tournaments.find(x=>String(x.id)===String(tid));
  if(!t||t.format!=='Squad vs Squad')return error('INVALID TOURNAMENT','This is not a Squad-vs-Squad tournament.');
  if(!stLeaderCodeValid(t))return error('INVITATION CODE EXPIRED','The initial Squad Leader access code is no longer valid because squad registration has closed.');
  if(String(code).trim().toUpperCase()!==String(t.leaderAccessCode).trim().toUpperCase())return error('INVALID ACCESS CODE','The tournament invitation code is incorrect.');
  if(!squadName||!squadId)return error('SQUAD DETAILS REQUIRED','Enter the exact in-game Squad Name and Squad ID.');
  const list=communityDb.squadTournamentApprovals||[];
  if(list.some(a=>String(a.tournamentId)===String(tid)&&a.status==='Pending'&&String(a.leaderAccountId)===String(account.id)))return error('ALREADY SUBMITTED','Your Squad registration is already awaiting approval.');
  if(list.some(a=>String(a.tournamentId)===String(tid)&&a.status==='Approved'&&String(a.leaderAccountId)===String(account.id)))return error('ALREADY APPROVED','You already have an approved Squad registration for this tournament.');
  if(list.some(a=>String(a.tournamentId)===String(tid)&&a.status==='Approved'&&String(a.squadId).trim().toLowerCase()===String(squadId).trim().toLowerCase()))return error('SQUAD ALREADY REGISTERED','That Squad ID is already approved for this tournament.');
  const approvedCount=list.filter(a=>String(a.tournamentId)===String(tid)&&a.status==='Approved').length;
  if(approvedCount>=Number(t.squadSlots||0))return error('SQUAD SLOTS FULL','All configured Squad slots have already been approved.');
  const a={id:'STA'+Date.now()+Math.random().toString(36).slice(2,6),tournamentId:tid,tournamentTitle:t.title,squadName,squadId,leaderAccountId:account.id,leaderMemberId:null,leaderIgn:account.ign,leaderGameId:account.gameId,leaderServerId:account.serverId,role:'Squad Leader',status:'Pending',createdAt:new Date().toISOString(),maxSquads:Number(t.squadSlots||0),membersPerSquad:Number(t.membersPerSquad||7),memberAccessCode:null,memberAccessCodeExpiresAt:null};
  list.push(a);communityDb.squadTournamentApprovals=list;
  addCommunityNotification('squad_registration','Squad Tournament Approval Needed',`${squadName} (${squadId}), led by ${account.ign}, has submitted a Squad-vs-Squad registration for ${t.title}. Open ST Approval to review it.`);
  addCommunityNotification('squad_registration','Squad Registration Submitted',`Your squad registration for ${t.title} is awaiting Tournament Admin approval.`,account.id);
  saveCommunity();close();renderTournamentPage();
};

submitSTMemberRegistration=function(tid,code,account){
  const t=communityDb.tournaments.find(x=>String(x.id)===String(tid));
  if(!t||t.format!=='Squad vs Squad')return error('INVALID TOURNAMENT','This is not a Squad-vs-Squad tournament.');
  const normalized=String(code||'').trim().toUpperCase();
  const approval=(communityDb.squadTournamentApprovals||[]).find(a=>String(a.tournamentId)===String(tid)&&String(a.memberAccessCode||'').toUpperCase()===normalized&&a.status==='Approved');
  if(!approval)return error('INVALID SQUAD CODE','That Squad Member access code is invalid, expired, or the Squad has not been approved.');
  if(!stMemberCodeValid(t,approval))return error('SQUAD REGISTRATION CLOSED','This Squad has reached capacity or registration has closed.');
  if(communityDb.registrations.some(r=>String(r.tournamentId)===String(tid)&&String(r.accountId)===String(account.id)))return error('ALREADY REGISTERED','Your profile is already registered for this tournament.');
  const squadCount=communityDb.registrations.filter(r=>String(r.tournamentId)===String(tid)&&String(r.squadApprovalId)===String(approval.id)).length;
  const max=Number(t.membersPerSquad||approval.membersPerSquad||7);
  if(squadCount>=max)return error('SQUAD FULL',`This Squad is already full at ${max}/${max} members.`);
  const isSub=squadCount>=5;
  communityDb.registrations.push({id:'R'+Date.now()+Math.random().toString(36).slice(2,6),accountId:account.id,tournamentId:tid,ign:account.ign,gameId:account.gameId,serverId:account.serverId,status:'Registered',registeredAt:new Date().toISOString(),squadApprovalId:approval.id,squadName:approval.squadName,squadId:approval.squadId,squadRole:String(account.id)===String(approval.leaderAccountId)?'Squad Leader':'Squad Member',isSubstitute:isSub});
  saveCommunity();close();renderTournamentPage();show(`<div class="setup-lock"><div class="setup-icon">✓</div><span class="eyebrow">SQUAD REGISTRATION COMPLETE</span><h2>${esc(t.title)}</h2><p class="muted">${esc(account.ign)} is registered to <b>${esc(approval.squadName)}</b> as a ${isSub?'substitute':'starter'}.</p><div class="actions"><button class="primary" onclick="close();renderTournamentPage()">Done</button></div></div>`);
};

// Approval now creates the unique member code only after the Admin accepts the squad.
approveSTRequest=function(id){
  if(!tournamentAdminAccess())return error('ACCESS DENIED','Only the Squad Owner or an authorized Tournament Manager can approve Squad Tournament registrations.');
  const a=(communityDb.squadTournamentApprovals||[]).find(x=>String(x.id)===String(id));
  if(!a)return error('REQUEST NOT FOUND','This Squad Tournament request could not be found.');
  if(a.status!=='Pending')return error('ALREADY DECIDED','This request has already been processed.');
  const t=communityDb.tournaments.find(x=>String(x.id)===String(a.tournamentId));
  if(!t||t.format!=='Squad vs Squad')return error('INVALID TOURNAMENT','This approval does not belong to a Squad-vs-Squad tournament.');
  if(!stLeaderCodeValid(t))return error('REGISTRATION CLOSED','The tournament no longer accepts new Squad approvals.');
  const approvedCount=(communityDb.squadTournamentApprovals||[]).filter(x=>String(x.tournamentId)===String(a.tournamentId)&&x.status==='Approved').length;
  if(approvedCount>=Number(t.squadSlots||0))return error('SQUAD SLOTS FULL','All configured Squad slots are already approved.');
  a.status='Approved';a.updatedAt=new Date().toISOString();a.approvedBy=current?.id||null;
  a.memberAccessCode=generateTournamentCode('DS-SQUAD');
  a.memberAccessCodeCreatedAt=new Date().toISOString();
  a.memberAccessCodeExpiresAt=stRegistrationDeadlineMs(t)===Infinity?null:new Date(stRegistrationDeadlineMs(t)).toISOString();
  t.approvedSquadCount=approvedCount+1;
  if(t.approvedSquadCount>=Number(t.squadSlots||0))t.squadRegistrationOpen=false;
  addCommunityNotification('squad_approval','Squad Tournament Approved',`Your squad ${a.squadName} has been approved for ${t.title}. Your unique member access code is ${a.memberAccessCode}. Send this code only to your pre-added squad members.`,a.leaderAccountId);
  saveCommunity();renderTournamentPage();
};

// Make ST Approval rows show the leader profile before approval.
const _stApprovalViewV13=stApprovalView;
stApprovalView=function(){
  const html=_stApprovalViewV13();
  return html.replace(/(<div class="tour-actions"><span class="tour-chip st-status-[^>]+>[^<]+<\/span>)(\s*)(<button class="small accent" onclick="approveSTRequest)/g,'$1$2<button class="small" onclick="viewSTLeaderProfile(\'PLACEHOLDER\')">View Profile</button>$2$3');
};
function viewSTLeaderProfile(id){
  const a=(communityDb.squadTournamentApprovals||[]).find(x=>String(x.id)===String(id));
  if(!a)return error('REQUEST NOT FOUND','That Squad Tournament request could not be found.');
  const acc=communityDb.accounts.find(x=>String(x.id)===String(a.leaderAccountId));
  show(`<div class="login-wrap registered-profile-modal"><span class="eyebrow">SQUAD LEADER PROFILE</span><h2>${esc(acc?.ign||a.leaderIgn||'Unknown')}</h2><p class="muted">View-only registration identity for ${esc(a.tournamentTitle||'Squad Tournament')}</p><div class="profile-data"><div><small>IGN</small><b>${esc(acc?.ign||a.leaderIgn||'—')}</b></div><div><small>GAME ID</small><b>${esc(acc?.gameId||a.leaderGameId||'—')}</b></div><div><small>SERVER ID</small><b>${esc(acc?.serverId||a.leaderServerId||'—')}</b></div><div><small>SQUAD</small><b>${esc(a.squadName||'—')}</b></div><div><small>SQUAD ID</small><b>${esc(a.squadId||'—')}</b></div><div><small>ROLE</small><b>Squad Leader</b></div></div><div class="notice"><b>View only</b><br><span>Approval staff can review the registration identity but cannot edit the member's personal profile.</span></div><div class="actions"><button class="ghost" onclick="close()">Close</button></div></div>`);
}

// Rebuild the approval view cleanly with real request IDs (the replacement above is only a safety net for older cached markup).
stApprovalView=function(){
  const approvals=communityDb.squadTournamentApprovals||[];
  const pending=approvals.filter(a=>(a.status||'Pending')==='Pending');
  const recent=approvals.filter(a=>(a.status||'Pending')!=='Pending').slice().sort((a,b)=>new Date(b.updatedAt||b.createdAt||0)-new Date(a.updatedAt||a.createdAt||0)).slice(0,12);
  const row=a=>{const status=a.status||'Pending';const t=communityDb.tournaments.find(x=>String(x.id)===String(a.tournamentId));return `<div class="tour-list-row st-approval-row"><div><b>${esc(a.squadName||'Unnamed Squad')}</b><div class="meta">Leader: ${esc(a.leaderIgn||'Unknown')} • Squad ID: ${esc(a.squadId||'—')} • ${esc(t?.title||a.tournamentTitle||'Squad Tournament')}</div><div class="meta">Submitted ${a.createdAt?esc(new Date(a.createdAt).toLocaleString()):'—'}</div></div><div class="tour-actions"><span class="tour-chip st-status-${status.toLowerCase()}">${esc(status)}</span><button class="small" onclick="viewSTLeaderProfile('${a.id}')">View Profile</button>${status==='Approved'&&a.memberAccessCode?`<button class="small" onclick="copyAccessCode('${esc(a.memberAccessCode)}',this)">Copy Member Code</button>`:''}${status==='Pending'?`<button class="small accent" onclick="approveSTRequest('${a.id}')">Approve</button><button class="small danger" onclick="rejectSTRequest('${a.id}')">Reject</button>`:''}</div></div>`};
  return `<section class="tour-admin-card st-approval-page"><div class="section-head"><div><span class="eyebrow">SQUAD TOURNAMENT</span><h2>ST Approval</h2><p class="muted">Approve authorized Squad Leader registrations. Approval reserves one Squad slot and creates the unique member code.</p></div><div class="tour-stat-card st-approval-count"><small>Pending Requests</small><b>${pending.length}</b></div></div><section class="st-approval-block"><div class="section-head"><div><h3>Pending Requests</h3><p class="muted">Review the exact in-game Squad Name, Squad ID and locked Squad Leader role before approving.</p></div></div><div class="tour-list">${pending.map(row).join('')||'<div class="tour-empty">No pending Squad Tournament approvals.</div>'}</div></section><section class="st-approval-block"><div class="section-head"><div><h3>Recent Decisions</h3><p class="muted">Approved and rejected requests remain visible for reference.</p></div></div><div class="tour-list">${recent.map(row).join('')||'<div class="tour-empty">No approval history yet.</div>'}</div></section></section>`;
};

// Extend the management summary so the owner can clearly see the two-stage access-code model.
const _v13ManageTournament= v64ManageTournament;
v64ManageTournament=function(id){
  _v13ManageTournament(id);
  const t=communityDb.tournaments.find(x=>String(x.id)===String(id));
  if(t?.format!=='Squad vs Squad')return;
  const modal=document.querySelector('#modal .login-wrap'); if(!modal)return;
  const old=modal.querySelector('.st-v13-summary'); if(old)return;
  const approvals=(communityDb.squadTournamentApprovals||[]).filter(a=>String(a.tournamentId)===String(id));
  modal.insertAdjacentHTML('afterbegin',`<div class="notice st-v13-summary" style="margin:14px 0"><b>Squad-vs-Squad access flow</b><br><span>1 initial leader code → leader submits squad → ST Approval → unique member code → community members register.</span><br><span>Initial leader code: <strong>${esc(t.leaderAccessCode)}</strong> <button type="button" class="small" onclick="copyAccessCode('${esc(t.leaderAccessCode)}',this)">Copy Code</button> • Approved squads: <strong>${approvals.filter(a=>a.status==='Approved').length}/${esc(t.squadSlots)}</strong></span></div>`);
};
tourManage=v64ManageTournament;

ensureV13SquadTournamentData();
saveCommunity();

/* V15: reliable modal actions + simple Community notification center */
(function(){
  // Inline buttons such as Done/Cancel call close(); bind the global browser name explicitly
  // so embedded/mobile webviews do not resolve it to the browser's window.close().
  window.close = function(){
    const modal=document.getElementById('modal');
    if(modal) modal.classList.remove('open','setup-mode','lock-overlay');
  };

  window.__notificationFilter = window.__notificationFilter || 'all';

  function visibleCommunityNotifications(){
    if(!communityCurrent) return [];
    return (communityDb.notifications||[]).filter(n=>
      !n.audienceId || String(n.audienceId)===String(communityCurrent.id)
    ).slice(0,50);
  }

  window.setNotificationFilter=function(filter){
    window.__notificationFilter=filter==='mine'?'mine':'all';
    const bar=document.getElementById('notificationBar');
    if(bar){ bar.outerHTML=notificationBarHtml(); bindCommunityNotificationActions(); }
  };

  window.notificationBarHtml=function(){
    const notes=visibleCommunityNotifications();
    const all=notes.filter(n=>!n.audienceId);
    const mine=notes.filter(n=>n.audienceId && communityCurrent && String(n.audienceId)===String(communityCurrent.id));
    const filter=window.__notificationFilter||'all';
    const shown=filter==='mine'?mine:all;
    const unread=notes.filter(n=>!n.read).length;
    const icon=(type)=>({cancelled:'×',removed:'−',reinstated:'↺',role:'★',squad_approval:'✓',squad_registration:'⌁'}[type]||'•');
    return `<div id="notificationBar" class="notification-bar ${shown.length?'':'empty'}">
      <div class="notification-bar-head">
        <div><span class="eyebrow">DARK SYSTEM</span><h3>Notifications</h3><p class="muted notification-subtitle">${unread?`${unread} unread`:'All caught up'}</p></div>
        <div class="notification-head-actions"><button type="button" class="ghost small" id="markCommunityNotificationsRead">Mark all read</button><button type="button" class="ghost small notification-close" id="closeCommunityNotifications" aria-label="Close notifications">×</button></div>
      </div>
      <div class="notification-tabs" role="tablist" aria-label="Notification filter">
        <button type="button" class="notification-filter ${filter==='all'?'active':''}" onclick="setNotificationFilter('all')">All <span>${all.length}</span></button>
        <button type="button" class="notification-filter ${filter==='mine'?'active':''}" onclick="setNotificationFilter('mine')">For You <span>${mine.length}</span></button>
      </div>
      <div class="notification-list">
        ${shown.map(n=>`<article class="notification-item ${n.read?'read':'unread'}" onclick="markOneCommunityNotificationRead('${esc(n.id)}')">
          <div class="notification-dot">${icon(n.type)}</div><div class="notification-copy"><b>${esc(n.title)}</b><p>${esc(n.body)}</p><small>${fmt(n.time)}</small></div>${n.read?'':'<span class="notification-unread-dot" aria-label="Unread"></span>'}
        </article>`).join('')||'<p class="muted notification-empty">No notifications in this section.</p>'}
      </div>
    </div>`;
  };

  function bindCommunityNotificationActions(){
    const mark=document.getElementById('markCommunityNotificationsRead');
    if(mark) mark.onclick=window.markNotificationsRead;
    const closeBtn=document.getElementById('closeCommunityNotifications');
    if(closeBtn) closeBtn.onclick=()=>document.getElementById('notificationBar')?.remove();
  }

  window.markOneCommunityNotificationRead=function(id){
    const n=(communityDb.notifications||[]).find(x=>String(x.id)===String(id));
    if(!n)return;
    if(n.audienceId && (!communityCurrent || String(n.audienceId)!==String(communityCurrent.id)))return;
    n.read=true; saveCommunity();
    const bar=document.getElementById('notificationBar'); if(bar)bar.outerHTML=notificationBarHtml();
    bindCommunityNotificationActions();
    refreshSiteMenu();
  };

  window.markNotificationsRead=function(){
    (communityDb.notifications||[]).forEach(n=>{
      if(!n.audienceId || (communityCurrent&&String(n.audienceId)===String(communityCurrent.id))) n.read=true;
    });
    saveCommunity();
    const bar=document.getElementById('notificationBar'); if(bar)bar.outerHTML=notificationBarHtml();
    bindCommunityNotificationActions();
    refreshSiteMenu();
  };

  window.toggleNotificationBar=function(){
    const host=document.querySelector('.tournament-shell')||document.querySelector('.community-dashboard');
    if(!host)return;
    const bar=document.getElementById('notificationBar');
    if(bar){bar.remove();return;}
    host.insertAdjacentHTML('afterbegin',notificationBarHtml());
    bindCommunityNotificationActions();
  };


  // Harden copy buttons: preserve the working fallback and provide explicit success feedback.
  window.copyAccessCode=function(code,button){
    const value=String(code||'').trim();
    if(!value){ error('NO CODE','There is no access code to copy.'); return; }
    const finish=()=>{
      if(button){
        const old=button.textContent;
        button.textContent='✓ Copied';
        button.disabled=true;
        setTimeout(()=>{button.textContent=old;button.disabled=false;},1400);
      }
    };
    const fail=()=>error('COPY FAILED','Your browser blocked clipboard access. Please press and hold the code to copy it manually.');
    try{
      if(navigator.clipboard && typeof navigator.clipboard.writeText==='function'){
        navigator.clipboard.writeText(value).then(finish).catch(()=>{try{fallbackCopy(value,finish)}catch(e){fail()}});
      }else{fallbackCopy(value,finish);}
    }catch(e){try{fallbackCopy(value,finish)}catch(err){fail()}}
  };

  // Ensure common modal action buttons always have a working event handler, even in webviews.
  document.addEventListener('click',function(e){
    const el=e.target.closest?.('#modal .done-action, #modal [data-action="done"]');
    if(el){e.preventDefault();window.close();}
    const cancel=e.target.closest?.('#modal [data-action="cancel"]');
    if(cancel){e.preventDefault();window.close();}
  });
  // Browser credential/autofill support: never attempt to read password-manager storage.
  // Forms can request browser autofill with autocomplete="email" / "current-password"; the browser controls access.

})();


/* V29: server-authoritative complex tournament/community workflows. */
async function v29Json(path, payload){
  try { return await api(path,{method:'POST',body:JSON.stringify(payload)}); }
  catch(e){ error('SERVER ERROR',e.message||'The server could not complete that action.'); return null; }
}
const _v29SubmitSTLeader=submitSTLeaderRegistration;
submitSTLeaderRegistration=async function(tid,squadName,squadId,code,account,member){
  const t=communityDb.tournaments.find(x=>String(x.id)===String(tid));
  if(!t||t.format!=='Squad vs Squad')return error('INVALID TOURNAMENT','This is not a Squad-vs-Squad tournament.');
  if(String(code).trim().toUpperCase()!==String(t.leaderAccessCode||'').trim().toUpperCase())return error('INVALID ACCESS CODE','The tournament invitation code is incorrect.');
  const r=await v29Json('/api/tournaments/squad-approval',{action:'submit_leader',tournamentId:tid,leaderAccountId:account.id,squad:{squadName,squadId,leaderIgn:account.ign,leaderGameId:account.gameId,leaderServerId:account.serverId}});
  if(!r)return; communityDb.squadTournamentApprovals=r.approvals||communityDb.squadTournamentApprovals; close(); renderTournamentPage();
};
const _v29ApproveST=approveSTRequest;
approveSTRequest=async function(id){
  if(!tournamentAdminAccess())return error('ACCESS DENIED','Only the Squad Owner or an authorized Tournament Manager can approve Squad Tournament registrations.');
  const a=communityDb.squadTournamentApprovals.find(x=>String(x.id)===String(id)); if(!a)return error('REQUEST NOT FOUND','This request could not be found.');
  const r=await v29Json('/api/tournaments/squad-approval',{action:'approve',tournamentId:a.tournamentId,approvalId:id}); if(!r)return;
  communityDb.squadTournamentApprovals=r.approvals||communityDb.squadTournamentApprovals;
  const i=communityDb.tournaments.findIndex(x=>String(x.id)===String(a.tournamentId)); if(i>=0&&r.tournament)communityDb.tournaments[i]=r.tournament;
  renderTournamentPage();
};
const _v29RejectST=rejectSTRequest;
rejectSTRequest=async function(id){
  if(!tournamentAdminAccess())return error('ACCESS DENIED','Only the Squad Owner or an authorized Tournament Manager can reject Squad Tournament registrations.');
  const a=communityDb.squadTournamentApprovals.find(x=>String(x.id)===String(id)); if(!a)return error('REQUEST NOT FOUND','This request could not be found.');
  const r=await v29Json('/api/tournaments/squad-approval',{action:'reject',tournamentId:a.tournamentId,approvalId:id}); if(!r)return;
  communityDb.squadTournamentApprovals=r.approvals||communityDb.squadTournamentApprovals; renderTournamentPage();
};
const _v29ApproveResult=ownerApproveResult;
ownerApproveResult=async function(tid,mid){
  if(!tournamentAdminAccess())return error('ACCESS DENIED','You do not have Tournament Manager permission.');
  const r=await v29Json('/api/tournaments/result-review',{action:'approve',tournamentId:tid,matchId:mid}); if(!r)return;
  const i=communityDb.tournaments.findIndex(x=>String(x.id)===String(tid)); if(i>=0&&r.tournament)communityDb.tournaments[i]=r.tournament;
  communityDb.seasonPoints=communityDb.seasonPoints||{}; renderTournamentPage(); renderPublic();
};
const _v29RejectResult=ownerRejectResult;
ownerRejectResult=async function(tid,mid){
  if(!tournamentAdminAccess())return error('ACCESS DENIED','You do not have Tournament Manager permission.');
  const r=await v29Json('/api/tournaments/result-review',{action:'reject',tournamentId:tid,matchId:mid}); if(!r)return;
  const i=communityDb.tournaments.findIndex(x=>String(x.id)===String(tid)); if(i>=0&&r.tournament)communityDb.tournaments[i]=r.tournament;
  renderTournamentPage();
};
const _v29RecordEvent=recordEventParticipation;
recordEventParticipation=async function(eventId){
  if(!communityCurrent)return communityAuth();
  const r=await v29Json('/api/community/event-participation',{eventId}); if(!r)return;
  communityDb.eventParticipation=r.eventParticipation||communityDb.eventParticipation; communityDb.seasonPoints=r.seasonPoints||communityDb.seasonPoints;
  renderPublic(); close(); show(`<div class="setup-lock"><div class="setup-icon">✓</div><span class="eyebrow">PARTICIPATION RECORDED</span><h2>+50 Community Points</h2><p class="muted">Your participation has been added to the ${esc(communityDb.currentSeason||'current')} Community Leaderboard.</p><div class="actions"><button class="primary" onclick="close()">Done</button></div></div>`);
};
