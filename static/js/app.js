/* ===== SISTEMA DE ESTUDOS - TIAGO — JS Principal ===== */

const API = '';  // mesma origem

// Usuário ativo (selecionado na tela inicial)
let USUARIO = localStorage.getItem('usuario') || null;

// Estado global
let state = {
  stats: null,
  materias: [],
  trimestres: [],
  quiz: {
    perguntas: [],
    atual: 0,
    certas: 0,
    erradas: 0,
    erradasDetalhes: [],
    ativa: false
  },
  ultimaAulaId: null,
  bernoulliConteudos: []
};

// ─── Init ─────────────────────────────────────────────────────────────────────

// ─── Frases dos 3 Clubes ──────────────────────────────────────────────────────

const FRASES_CLUBES = [
  { clube: 'Grêmio 🔵⚫⚪',    frase: 'É Tri no Olímpico! Bora estudar!' },
  { clube: 'Grêmio 🔵⚫⚪',    frase: 'Garra Tricolor dentro e fora da sala!' },
  { clube: 'Grêmio 🔵⚫⚪',    frase: 'Renato Gaúcho sempre escalou quem treinou mais!' },
  { clube: 'Brasil 🇧🇷',       frase: 'Futebol arte começa nos estudos!' },
  { clube: 'Brasil 🇧🇷',       frase: 'A Amarelinha representa quem se prepara!' },
  { clube: 'Brasil 🇧🇷',       frase: 'Pelé estudou o adversário. Você estuda a matéria!' },
  { clube: 'Liverpool 🔴',     frase: 'You\'ll Never Walk Alone — nem nos estudos!' },
  { clube: 'Liverpool 🔴',     frase: 'Anfield vibra com quem nunca desiste!' },
  { clube: 'Liverpool 🔴',     frase: 'Salah treina todo dia. E você?' },
];

const LOADING_MSGS = [
  '⚽ Aquecendo para o jogo...',
  '🔵⚫⚪ Preparando a Arena Grêmio...',
  '🇧🇷 Convocando o time do conhecimento...',
  '🔴 Anfield está esperando por você...',
  '🏆 Carregando o campo de estudos...',
];

window.addEventListener('load', async () => {
  if (!USUARIO) {
    document.getElementById('loading-screen').classList.add('hidden');
    document.getElementById('user-select-screen').classList.remove('hidden');
    return;
  }
  iniciarApp();
});

function selecionarUsuario(nome) {
  USUARIO = nome;
  localStorage.setItem('usuario', nome);
  document.getElementById('user-select-screen').classList.add('hidden');
  iniciarApp();
}

function trocarUsuario() {
  localStorage.removeItem('usuario');
  USUARIO = null;
  location.reload();
}

async function iniciarApp() {
  // Mensagem aleatória no loading
  const loadMsg = LOADING_MSGS[Math.floor(Math.random() * LOADING_MSGS.length)];
  const msgEl = document.getElementById('loading-msg');
  if (msgEl) msgEl.textContent = loadMsg;
  document.getElementById('loading-screen').classList.remove('hidden');

  // Nome do usuário no header
  const nomeDisplay = USUARIO.charAt(0).toUpperCase() + USUARIO.slice(1);
  const headerName = document.getElementById('header-name');
  if (headerName) headerName.textContent = nomeDisplay;

  // Definir data de hoje nos inputs
  const hoje = new Date().toISOString().split('T')[0];
  document.getElementById('input-data').value = hoje;

  try {
    await Promise.all([
      carregarMaterias(),
      carregarStats()
    ]);
  } catch(e) {
    console.error('Erro ao carregar dados:', e);
  }

  // Esconder loading
  document.getElementById('loading-screen').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');

  // Registrar Service Worker e ativar notificações
  registrarServiceWorker();
}

// ─── Push Notifications ───────────────────────────────────────────────────────

async function registrarServiceWorker() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
  try {
    const reg = await navigator.serviceWorker.register('/static/sw.js');
    await navigator.serviceWorker.ready;
    await ativarPush(reg);
  } catch (e) {
    console.error('PUSH ERRO SW:', e.name, e.message);
  }
}

async function ativarPush(regParam) {
  try {
    let reg = regParam;
    if (!reg) {
      reg = await navigator.serviceWorker.ready;
    }
    if (Notification.permission === 'default') {
      const perm = await Notification.requestPermission();
      if (perm !== 'granted') return 'permissao_negada';
    }
    if (Notification.permission !== 'granted') return 'permissao_bloqueada';

    let sub = await reg.pushManager.getSubscription();
    if (sub) await sub.unsubscribe();

    const keyRes = await fetch('/api/push/vapid-public-key');
    const { publicKey } = await keyRes.json();
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey)
    });

    const subJson = sub.toJSON();
    const res = await fetch('/api/push/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        usuario: USUARIO,
        endpoint: subJson.endpoint,
        p256dh: subJson.keys.p256dh,
        auth: subJson.keys.auth
      })
    });
    return res.ok ? 'ok' : 'erro_servidor';
  } catch (e) {
    console.error('PUSH ERRO:', e.name, e.message);
    return e.name + ': ' + e.message;
  }
}

// Chamado pelo botão de notificações nas configurações
window.ativarNotificacoes = async function() {
  const btn = document.getElementById('btn-notif');
  if (btn) btn.textContent = 'Ativando...';
  const timeout = new Promise(resolve => setTimeout(() => resolve('timeout_30s'), 30000));
  const resultado = await Promise.race([ativarPush(), timeout]);
  if (btn) {
    if (resultado === 'ok') {
      btn.textContent = '✅ Notificações ativas!';
      btn.style.background = '#27AE60';
    } else {
      btn.textContent = '❌ ' + resultado;
      btn.style.background = '#E74C3C';
      btn.style.fontSize = '12px';
    }
  }
};

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - base64String.length % 4) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
}

// ─── API Helpers ──────────────────────────────────────────────────────────────

async function get(url) {
  const sep = url.includes('?') ? '&' : '?';
  const res = await fetch(API + url + sep + 'usuario=' + USUARIO);
  return res.json();
}

async function post(url, data) {
  const res = await fetch(API + url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ usuario: USUARIO, ...data })
  });
  return res.json();
}

// ─── Navegação ────────────────────────────────────────────────────────────────

function showTab(tab) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.getElementById(`section-${tab}`).classList.add('active');
  document.getElementById(`tab-${tab}`).classList.add('active');

  if (tab === 'materias') { renderMateriasDetalhe(); carregarDificuldades(); }
  if (tab === 'home') carregarStats();
  if (tab === 'prova') carregarHistoricoGuias();
  if (tab === 'hoje') carregarPainelDia();
  if (tab === 'quiz') carregarRevisaoSemana();
}

// ─── Carregar Dados ───────────────────────────────────────────────────────────

async function carregarMaterias() {
  const data = await get('/api/materias');
  state.materias = data.materias;
  state.trimestres = data.trimestres;

  // Preencher selects
  const selMateria = document.getElementById('input-materia');
  const quizMateria = document.getElementById('quiz-materia');
  const provaMateria = document.getElementById('prova-materia');
  data.materias.forEach(m => {
    if (selMateria) selMateria.innerHTML += `<option value="${m}">${m}</option>`;
    if (quizMateria) quizMateria.innerHTML += `<option value="${m}">${m}</option>`;
    if (provaMateria) provaMateria.innerHTML += `<option value="${m}">${m}</option>`;
  });
}

async function carregarStats() {
  const data = await get('/api/stats');
  state.stats = data;

  // Header
  const xp = data.total_aulas * 50 + data.total_respostas * 10;
  document.getElementById('xp-total').textContent = `${xp} XP`;
  document.getElementById('streak-num').textContent = data.streak_atual;

  // Nível — progressão entre os três clubes do Tiago
  const niveis = [
    '⚽ Garoto da Base',          // 0–499 XP
    '🔵⚫⚪ Revelação do Grêmio',   // 500–999
    '🟡🟢 Convocado pela Seleção', // 1000–1499
    '🔴 Cria de Liverpool',        // 1500–1999
    '🏆 Titular do Grêmio',        // 2000–2499
    '🇧🇷 Camisa 10 do Brasil',     // 2500–2999
    '⭐ Ídolo de Anfield',         // 3000–3499
    '🌟 Lenda das Três Camisas'    // 3500+
  ];
  const nivel = niveis[Math.min(Math.floor(xp / 500), niveis.length - 1)];
  document.getElementById('header-nivel').textContent = nivel;

  // Banner — frase aleatória dos 3 clubes
  const hora = new Date().getHours();
  let saudacao = hora < 12 ? 'Bom dia' : hora < 18 ? 'Boa tarde' : 'Boa noite';
  const fraseHoje = FRASES_CLUBES[new Date().getDate() % FRASES_CLUBES.length];
  const nomeExibir = USUARIO.charAt(0).toUpperCase() + USUARIO.slice(1);
  document.getElementById('banner-title').textContent =
    data.streak_atual > 0
      ? `${saudacao}, ${nomeExibir}! 🔥 ${data.streak_atual} dias seguidos!`
      : `${saudacao}, ${nomeExibir}! ${fraseHoje.frase}`;
  document.getElementById('banner-sub').textContent =
    data.total_aulas === 0
      ? `${fraseHoje.clube} — Registre sua primeira aula agora`
      : `${data.total_aulas} aulas • ${data.taxa_acerto}% de acerto • ${fraseHoje.clube}`;

  // Cards stats
  document.getElementById('stat-aulas').textContent = data.total_aulas;
  document.getElementById('stat-taxa').textContent = `${data.taxa_acerto}%`;
  document.getElementById('stat-dias').textContent = data.dias_estudados_mes;
  document.getElementById('stat-quiz').textContent = data.total_respostas;

  // Progresso por matéria
  const maxAulas = Math.max(...data.por_materia.map(m => m.total_aulas), 1);
  const listEl = document.getElementById('materias-progress');
  if (data.por_materia.length === 0) {
    listEl.innerHTML = '<div class="empty-state"><div class="empty-icon">📚</div><p>Nenhuma aula ainda.<br>Registre seu primeiro treino!</p></div>';
  } else {
    listEl.innerHTML = data.por_materia.slice(0, 6).map(m => {
      const pct = Math.round((m.total_aulas / maxAulas) * 100);
      return `
        <div class="materia-item">
          <div class="materia-item-header">
            <div class="materia-nome">${m.materia}</div>
            <div class="materia-count">${m.total_aulas} aula${m.total_aulas !== 1 ? 's' : ''}</div>
          </div>
          <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
        </div>
      `;
    }).join('');
  }

  // Últimas aulas
  const aulasEl = document.getElementById('ultimas-aulas');
  if (data.ultimas_aulas.length === 0) {
    aulasEl.innerHTML = '<div style="color:#999;font-size:13px;text-align:center;padding:16px">Nenhuma aula registrada ainda.</div>';
  } else {
    aulasEl.innerHTML = data.ultimas_aulas.map(a => `
      <div class="aula-card" onclick="verAula(${a.id})">
        <div class="aula-card-header">
          <div class="aula-materia">${a.materia}</div>
          <div class="aula-data">${formatarData(a.data)}</div>
        </div>
        ${a.capitulo ? `<div class="aula-capitulo">📖 ${a.capitulo}</div>` : ''}
        <div class="aula-resumo">${(a.resumo || '').substring(0, 120)}${(a.resumo || '').length > 120 ? '...' : ''}</div>
        <span class="aula-trimestre">${a.trimestre}</span>
      </div>
    `).join('');
  }
}


// ─── Registrar Aula ───────────────────────────────────────────────────────────

async function registrarAula(event, acao = 'proximo') {
  event.preventDefault();

  const btnProx = document.getElementById('btn-salvar-proximo');
  const btnFin  = document.getElementById('btn-finalizar-dia');
  if (btnProx) { btnProx.disabled = true; btnProx.innerHTML = '<span class="spinner"></span> Gerando...'; }
  if (btnFin)  { btnFin.disabled = true; }

  const pIni = document.getElementById('input-pagina-ini').value;
  const pFim = document.getElementById('input-pagina-fim').value;
  const data = {
    data: document.getElementById('input-data').value,
    materia: document.getElementById('input-materia').value,
    trimestre: document.getElementById('input-trimestre').value,
    capitulo: document.getElementById('input-capitulo').value,
    pagina_ini: pIni ? parseInt(pIni) : null,
    pagina_fim: pFim ? parseInt(pFim) : null,
    conteudo: document.getElementById('input-conteudo').value,
    fonte: 'manual'
  };

  try {
    // Enviar todas as fotos ANTES da aula para o Claude poder usá-las
    for (const file of fotosAcumuladas) {
      const formData = new FormData();
      formData.append('file', file);
      await fetch('/api/upload', { method: 'POST', body: formData });
    }

    const result = await post('/api/aulas', data);
    state.ultimaAulaId = result.id;

    // Salvar data e trimestre antes de resetar
    const dataAtual = document.getElementById('input-data').value;
    const trimestreAtual = document.getElementById('input-trimestre').value;

    // Limpar form (exceto data e trimestre)
    document.getElementById('form-aula').reset();
    document.getElementById('input-data').value = dataAtual;
    document.getElementById('input-trimestre').value = trimestreAtual;
    limparFotos();

    // Recarregar stats
    await carregarStats();

    if (acao === 'finalizar') {
      // Ir para o painel do dia
      showTab('hoje');
    } else {
      // Mostrar modal de sucesso e permanecer no Treino
      document.getElementById('modal-resumo').innerHTML = formatarTexto(result.resumo);
      document.getElementById('modal-sucesso').classList.remove('hidden');
      document.getElementById('modal-overlay').classList.remove('hidden');
    }

  } catch(e) {
    alert('Erro ao registrar aula. Tente novamente.');
    console.error(e);
  }

  if (btnProx) { btnProx.disabled = false; btnProx.innerHTML = '💾 Salvar e adicionar próxima'; }
  if (btnFin)  { btnFin.disabled = false; }
}

// ─── Upload Preview ───────────────────────────────────────────────────────────

// Armazena todas as fotos acumuladas
let fotosAcumuladas = [];
let fotosProva = [];

function adicionarFotos(input) {
  const preview = document.getElementById('foto-preview');
  if (input.files && input.files.length > 0) {
    Array.from(input.files).forEach(file => {
      fotosAcumuladas.push(file);
      const reader = new FileReader();
      const idx = fotosAcumuladas.length;
      reader.onload = e => {
        preview.innerHTML += `<img src="${e.target.result}" alt="Foto ${idx}" style="margin:4px;max-width:100px;max-height:100px;border-radius:8px;object-fit:cover;">`;
      };
      reader.readAsDataURL(file);
    });
  }
}

function adicionarFotosProva(input) {
  const preview = document.getElementById('prova-foto-preview');
  if (input.files && input.files.length > 0) {
    Array.from(input.files).forEach(file => {
      fotosProva.push(file);
      const reader = new FileReader();
      const idx = fotosProva.length;
      reader.onload = e => {
        preview.innerHTML += `<img src="${e.target.result}" alt="Foto ${idx}" style="margin:4px;max-width:100px;max-height:100px;border-radius:8px;object-fit:cover;">`;
      };
      reader.readAsDataURL(file);
    });
  }
}

function limparFotos() {
  fotosAcumuladas = [];
  document.getElementById('foto-preview').innerHTML = '';
}


// ─── Modal ────────────────────────────────────────────────────────────────────

function fecharModal() {
  document.getElementById('modal-sucesso').classList.add('hidden');
  document.getElementById('modal-overlay').classList.add('hidden');
}

function irParaQuiz() {
  fecharModal();
  showTab('hoje');
}

// ─── Ver aula ─────────────────────────────────────────────────────────────────

async function verAula(id) {
  // Por ora, apenas log — futuramente abre modal de detalhe
  console.log('Ver aula', id);
}

// ─── Quiz ─────────────────────────────────────────────────────────────────────

let modoQuiz = 'normal';

function setModoQuiz(modo) {
  modoQuiz = modo;
  document.getElementById('modo-normal-btn')?.classList.toggle('active', modo === 'normal');
  document.getElementById('modo-prova-btn')?.classList.toggle('active', modo === 'prova');
  document.getElementById('grupo-revisao-prova')?.classList.toggle('hidden', modo === 'normal');
}

async function iniciarQuiz() {
  const materia  = document.getElementById('quiz-materia')?.value || '';
  const trimestre = document.getElementById('quiz-trimestre')?.value || '';
  const limite   = parseInt(document.getElementById('quiz-limite')?.value || '10');
  const ateData   = document.getElementById('quiz-ate-data')?.value || '';
  const paginaIni = document.getElementById('quiz-pagina-ini')?.value || '';
  const paginaFim = document.getElementById('quiz-pagina-fim')?.value || '';

  const params = new URLSearchParams({ limite });
  if (materia)   params.append('materia', materia);
  if (trimestre) params.append('trimestre', trimestre);
  if (modoQuiz === 'prova') {
    if (ateData)   params.append('ate_data', ateData);
    if (paginaIni) params.append('pagina_ini', paginaIni);
    if (paginaFim) params.append('pagina_fim', paginaFim);
  }

  const data = await get(`/api/quiz?${params}`);

  if (!data.perguntas || data.perguntas.length === 0) {
    document.getElementById('quiz-sem-perguntas').classList.remove('hidden');
    return;
  }

  state.quiz = {
    perguntas: data.perguntas,
    atual: 0, certas: 0, erradas: 0,
    erradasDetalhes: [], ativa: true
  };

  document.getElementById('quiz-selector').classList.add('hidden');
  document.getElementById('quiz-resultado').classList.add('hidden');
  document.getElementById('quiz-game').classList.remove('hidden');

  renderPergunta();
}

function renderPergunta() {
  const q = state.quiz;
  const p = q.perguntas[q.atual];
  if (!p) return;

  // Header
  document.getElementById('q-atual').textContent = q.atual + 1;
  document.getElementById('q-total').textContent = q.perguntas.length;
  document.getElementById('score-certas').textContent = q.certas;
  document.getElementById('score-erradas').textContent = q.erradas;
  const badgeEl = document.getElementById('q-materia-badge');
  badgeEl.textContent = (p.revisao ? '🔄 Revisão — ' : '') + (p.materia || '');

  // Progress bar
  const pct = ((q.atual) / q.perguntas.length) * 100;
  document.getElementById('quiz-progress-fill').style.width = `${pct}%`;

  // Pergunta
  document.getElementById('q-texto').textContent = p.pergunta;

  // Alternativas
  const altsEl = document.getElementById('q-alternativas');
  const alternativas = typeof p.alternativas === 'string'
    ? JSON.parse(p.alternativas) : p.alternativas;

  altsEl.innerHTML = alternativas.map((alt, i) => `
    <button class="alternativa-btn" onclick="responder(${i})" data-idx="${i}">
      ${alt}
    </button>
  `).join('');

  // Esconder feedback
  document.getElementById('feedback-card').classList.add('hidden');
}

async function responder(indice) {
  const q = state.quiz;
  const p = q.perguntas[q.atual];

  // Desabilitar botões
  document.querySelectorAll('.alternativa-btn').forEach(btn => btn.disabled = true);

  // Marcar visualmente
  document.querySelectorAll('.alternativa-btn').forEach(btn => {
    const idx = parseInt(btn.dataset.idx);
    if (idx === p.correta) btn.classList.add('correta');
    else if (idx === indice && indice !== p.correta) btn.classList.add('errada');
  });

  // Enviar resposta para API
  let result = { correta: indice === p.correta, explicacao: p.explicacao || '' };
  try {
    const res = await post('/api/quiz/responder', { pergunta_id: p.id, resposta: indice });
    if (res && typeof res.correta !== 'undefined') result = res;
  } catch(e) { /* usa resultado local calculado acima */ }

  const acertou = result.correta;
  if (acertou) {
    q.certas++;
  } else {
    q.erradas++;
    q.erradasDetalhes.push({
      pergunta: p.pergunta,
      correta: (typeof p.alternativas === 'string'
        ? JSON.parse(p.alternativas) : p.alternativas)[p.correta]
    });
  }

  // Feedback — sempre aparece independente da API
  const feedbackEl = document.getElementById('feedback-card');
  const feedbackIcon = document.getElementById('feedback-icon');
  const feedbackTitulo = document.getElementById('feedback-titulo');
  const feedbackExp = document.getElementById('feedback-explicacao');

  feedbackIcon.textContent = acertou ? '✅' : '❌';
  feedbackTitulo.textContent = acertou
    ? 'Gol! Resposta correta! ⚽'
    : 'Fora! Resposta incorreta';
  feedbackTitulo.className = 'feedback-titulo ' + (acertou ? 'certa' : 'errada');
  feedbackExp.textContent = result.explicacao || p.explicacao || '';

  // Botão próxima
  const isUltima = q.atual >= q.perguntas.length - 1;
  feedbackEl.querySelector('button').textContent = isUltima ? '🏁 Ver Resultado' : 'Próxima ▶';

  feedbackEl.classList.remove('hidden');
  feedbackEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  // Atualizar scores no header
  document.getElementById('score-certas').textContent = q.certas;
  document.getElementById('score-erradas').textContent = q.erradas;
}

function proximaPergunta() {
  const q = state.quiz;
  const isUltima = q.atual >= q.perguntas.length - 1;

  if (isUltima) {
    mostrarResultado();
    return;
  }

  q.atual++;
  renderPergunta();
}

function mostrarResultado() {
  const q = state.quiz;
  const total = q.certas + q.erradas;
  const taxa = total > 0 ? Math.round((q.certas / total) * 100) : 0;

  document.getElementById('quiz-game').classList.add('hidden');
  document.getElementById('quiz-resultado').classList.remove('hidden');

  document.getElementById('res-certas').textContent = q.certas;
  document.getElementById('res-erradas').textContent = q.erradas;
  document.getElementById('resultado-taxa').textContent = `${taxa}% de aproveitamento`;

  // Ícone e mensagem por performance — rodízio entre Grêmio, Seleção e Liverpool
  const msgs90 = [
    { icone: '🏆', titulo: 'É Tri no Olímpico!', msg: 'Desempenho de Grêmio levantando a Libertadores! Você é craque demais, Tiago! 🔵⚫⚪' },
    { icone: '🇧🇷', titulo: 'Seleção Raiz!', msg: 'Nota 10! Você jogou como a Seleção em 70 — futebol arte no mais alto nível! 🟡🟢' },
    { icone: '🔴', titulo: 'You\'ll Never Walk Alone!', msg: 'Anfield vibrou! Desempenho de Liverpool campeão da Champions! Incrível! ⭐' }
  ];
  const msgs70 = [
    { icone: '⚽', titulo: 'Titular garantido!', msg: 'Bom jogo! Com esse ritmo, o Renato Gaúcho te escala semana que vem! 🔵⚫⚪' },
    { icone: '🟡', titulo: 'Na seleção pré-convocados!', msg: 'Tite ficaria orgulhoso! Mais um treino e você vira titular da Amarelinha. 🇧🇷' },
    { icone: '🔴', titulo: 'Klopp aprovou!', msg: 'O técnico viu seu quiz e já pediu seu contrato para Anfield. Continue assim! ⭐' }
  ];
  const msgs50 = [
    { icone: '💪', titulo: 'Na luta pela vaga!', msg: 'Até o Ronaldinho Gaúcho foi da base antes de ser ídolo. Você está no caminho certo! 🔵⚫⚪' },
    { icone: '🇧🇷', titulo: 'Treino da Seleção!', msg: 'Todo craque passa pela categoria de base. Revise o conteúdo e sobe no ranking! 🟡🟢' },
    { icone: '🔴', titulo: 'Pré-temporada em Anfield!', msg: 'Liverpool também treina muito antes de ganhar títulos. Bora revisar e evoluir! ⭐' }
  ];
  const msgs0 = [
    { icone: '📚', titulo: 'De volta ao treino!', msg: 'Nem Messi acertou tudo de primeira. Releia o conteúdo e desafie o quiz de novo! 💪' },
    { icone: '🎽', titulo: 'Campo de treinamento!', msg: 'Até Salah errou gols importantes. O que importa é treinar e voltar mais forte! 🔴' },
    { icone: '⚽', titulo: 'Revisão obrigatória!', msg: 'O Grêmio passou por rebaixamento e voltou campeão. Você também vai virar a chave! 🔵⚫⚪' }
  ];

  const pick = arr => arr[Math.floor(Math.random() * arr.length)];
  let escolha;
  if (taxa >= 90)      escolha = pick(msgs90);
  else if (taxa >= 70) escolha = pick(msgs70);
  else if (taxa >= 50) escolha = pick(msgs50);
  else                 escolha = pick(msgs0);

  let { icone, titulo, msg } = escolha;

  document.getElementById('resultado-icon').textContent = icone;
  document.getElementById('resultado-titulo').textContent = titulo;
  document.getElementById('resultado-msg').textContent = msg;

  // Revisão das erradas
  const revisaoEl = document.getElementById('revisao-erradas');
  if (q.erradasDetalhes.length > 0) {
    revisaoEl.innerHTML = `
      <div class="section-title" style="margin-top:16px">📋 Revise estas respostas:</div>
      ${q.erradasDetalhes.map(e => `
        <div class="revisao-errada-item">
          <div class="pergunta">❓ ${e.pergunta}</div>
          <div class="resp-certa">✅ Certa: ${e.correta}</div>
        </div>
      `).join('')}
    `;
  } else {
    revisaoEl.innerHTML = '';
  }
}

function reiniciarQuiz() {
  state.quiz = { perguntas: [], atual: 0, certas: 0, erradas: 0, erradasDetalhes: [], ativa: false };
  document.getElementById('quiz-game').classList.add('hidden');
  document.getElementById('quiz-resultado').classList.add('hidden');
  document.getElementById('quiz-resumo-tela').classList.add('hidden');
  document.getElementById('quiz-selector').classList.remove('hidden');
  quizDiaData = null;
}

// ─── Revisão espaçada ─────────────────────────────────────────────────────────

async function iniciarRevisao() {
  const data = await get('/api/quiz/revisao');
  if (!data.perguntas || data.perguntas.length === 0) {
    alert('Nenhuma pergunta para revisar! Faça mais quizzes primeiro.');
    return;
  }

  state.quiz = {
    perguntas: data.perguntas,
    atual: 0, certas: 0, erradas: 0,
    erradasDetalhes: [], ativa: true
  };

  showTab('quiz');
  document.getElementById('quiz-selector').classList.add('hidden');
  document.getElementById('quiz-resultado').classList.add('hidden');
  document.getElementById('quiz-game').classList.remove('hidden');
  renderPergunta();
}

// ─── Matérias Detalhe ─────────────────────────────────────────────────────────

async function renderMateriasDetalhe() {
  const el = document.getElementById('materias-detalhe');
  el.innerHTML = '<div style="text-align:center;padding:20px;color:#999">Carregando...</div>';

  const data = await get('/api/aulas');
  const porMateria = {};
  data.aulas.forEach(a => {
    if (!porMateria[a.materia]) porMateria[a.materia] = [];
    porMateria[a.materia].push(a);
  });

  if (Object.keys(porMateria).length === 0) {
    el.innerHTML = '<div class="empty-state"><div class="empty-icon">📚</div><p>Nenhuma aula registrada ainda.</p></div>';
    return;
  }

  el.innerHTML = Object.entries(porMateria).map(([materia, aulas]) => `
    <div class="materia-detalhe-card">
      <div class="materia-detalhe-header">
        <div class="materia-detalhe-nome">${materia}</div>
        <div class="materia-detalhe-stats">${aulas.length} aula${aulas.length !== 1 ? 's' : ''}</div>
      </div>
      <div class="materia-detalhe-body">
        ${aulas.slice(0, 5).map(a => `
          <div class="materia-aula-mini">
            <div class="mini-dot"></div>
            <div class="mini-texto">
              <div>${a.capitulo || a.trimestre}</div>
              <div class="mini-data">${formatarData(a.data)}</div>
            </div>
          </div>
        `).join('')}
        ${aulas.length > 5 ? `<div style="font-size:12px;color:#999;text-align:center;padding-top:8px">+${aulas.length - 5} mais aulas</div>` : ''}
      </div>
    </div>
  `).join('');
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatarData(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr + 'T12:00:00');
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
}

function formatarTexto(texto) {
  if (!texto) return '';
  return texto
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');
}

// ─── Guia de Prova ────────────────────────────────────────────────────────────

async function gerarGuiaProva(event) {
  event.preventDefault();
  const btn = document.getElementById('btn-gerar-guia');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Gerando guia completo...';

  const pIni = document.getElementById('prova-pagina-ini').value;
  const pFim = document.getElementById('prova-pagina-fim').value;
  const materia  = document.getElementById('prova-materia').value;
  const trimestre = document.getElementById('prova-trimestre').value;

  const dados = {
    materia,
    trimestre,
    topicos: document.getElementById('prova-topicos').value,
    pagina_ini: pIni ? parseInt(pIni) : null,
    pagina_fim: pFim ? parseInt(pFim) : null,
    conteudo_extra: document.getElementById('prova-conteudo').value
  };

  try {
    for (const file of fotosProva) {
      const formData = new FormData();
      formData.append('file', file);
      await fetch('/api/upload', { method: 'POST', body: formData });
    }
    const result = await post('/api/guia-prova', dados);
    mostrarGuia(result.guia_html, materia, trimestre, pIni, pFim);
    fotosProva = [];
    document.getElementById('prova-foto-preview').innerHTML = '';
  } catch(e) {
    alert('Erro ao gerar guia. Tente novamente.');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '🎯 Gerar Guia de Estudo';
  }
}

function mostrarGuia(html, materia, trimestre, pIni, pFim) {
  document.getElementById('prova-form-area').classList.add('hidden');
  document.getElementById('prova-guia-area').classList.remove('hidden');

  const pages = (pIni && pFim) ? ` • Págs. ${pIni}–${pFim}` : '';
  document.getElementById('guia-titulo').textContent = `${materia} — ${trimestre}`;
  document.getElementById('guia-sub').textContent = `Guia de estudo para prova${pages}`;
  document.getElementById('guia-conteudo').innerHTML = html;

  carregarHistoricoGuias();
}

function imprimirGuia() {
  const titulo = document.getElementById('guia-titulo').textContent;
  const sub = document.getElementById('guia-sub').textContent;
  const conteudo = document.getElementById('guia-conteudo').innerHTML;
  const win = window.open('', '_blank');
  win.document.write(`<!DOCTYPE html><html lang="pt-BR"><head>
    <meta charset="UTF-8"><title>${titulo}</title>
    <style>
      body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; color: #111; }
      h1 { font-size: 20px; margin-bottom: 4px; }
      .sub { color: #555; font-size: 14px; margin-bottom: 20px; }
      .guia-secao { border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
      .guia-secao.destaque { background: #fffbea; border-color: #f0c040; }
      .guia-secao.alerta { background: #fff0f0; border-color: #e05050; }
      .guia-secao h3 { margin: 0 0 10px; font-size: 15px; }
      table { width: 100%; border-collapse: collapse; font-size: 13px; }
      th { background: #003DA5; color: white; padding: 6px 10px; text-align: left; }
      td { padding: 6px 10px; border-bottom: 1px solid #eee; }
      tr:nth-child(even) td { background: #f8f8f8; }
      @media print { body { padding: 0; } }
    </style>
  </head><body>
    <h1>${titulo}</h1><div class="sub">${sub}</div>
    ${conteudo}
    <script>window.onload=()=>window.print();<\/script>
  </body></html>`);
  win.document.close();
}

function novoGuia() {
  document.getElementById('prova-form-area').classList.remove('hidden');
  document.getElementById('prova-guia-area').classList.add('hidden');
  document.getElementById('form-prova').reset();
}

async function carregarHistoricoGuias() {
  const data = await get('/api/guia-prova');
  if (!data.guias || data.guias.length === 0) return;

  document.getElementById('prova-historico').classList.remove('hidden');
  const lista = document.getElementById('lista-guias');
  lista.innerHTML = data.guias.map(g => {
    const pages = (g.pagina_ini && g.pagina_fim) ? ` • Págs. ${g.pagina_ini}–${g.pagina_fim}` : '';
    const data_fmt = g.criado_em ? g.criado_em.substring(0,10) : '';
    return `<div class="guia-card" onclick="abrirGuia(${g.id})">
      <div class="guia-card-titulo">${g.materia} — ${g.trimestre}</div>
      <div class="guia-card-sub">${g.topicos.substring(0,60)}...${pages} • ${data_fmt}</div>
    </div>`;
  }).join('');
}

async function abrirGuia(id) {
  const guia = await get(`/api/guia-prova/${id}`);
  const pages = (guia.pagina_ini && guia.pagina_fim) ? ` • Págs. ${guia.pagina_ini}–${guia.pagina_fim}` : '';
  mostrarGuia(guia.guia_html, guia.materia, guia.trimestre,
    guia.pagina_ini, guia.pagina_fim);
}

// ─── Painel do Dia ────────────────────────────────────────────────────────────

const EMOJIS_MATERIA = {
  'Matemática': '📐', 'Física': '⚛️', 'Química': '🧪', 'Biologia': '🧬',
  'História': '🏛️', 'Geografia': '🌍', 'Filosofia': '💭', 'Sociologia': '👥',
  'Língua Portuguesa': '📝', 'Literatura': '📚', 'Arte': '🎨',
  'Língua Inglesa': '🇬🇧', 'Língua Espanhola': '🇪🇸',
  'Ciências': '🔬', 'Educação Digital': '💻', 'Educação Física': '⚽',
  'Ensino Religioso': '🙏', 'Redação': '✍️'
};

function emojiMateria(materia) {
  return EMOJIS_MATERIA[materia] || '📖';
}

async function carregarPainelDia() {
  const hoje = new Date().toISOString().split('T')[0];
  document.getElementById('hoje-data-label').textContent =
    'Aulas de ' + new Date(hoje + 'T12:00:00').toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long' });

  const data = await get('/api/aulas/dia');
  const aulas = data.aulas || [];
  const cardsEl = document.getElementById('hoje-cards');
  const topoEl  = document.getElementById('hoje-resumo-topo');

  if (aulas.length === 0) {
    topoEl.innerHTML = '';
    cardsEl.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">📋</div>
        <p>Nenhuma aula registrada hoje.<br>Vá para <strong>Treino</strong> e registre!</p>
        <button class="btn-primary" style="margin-top:16px" onclick="showTab('registrar')">📝 Ir para Treino</button>
      </div>`;
    return;
  }

  const concluidas = aulas.filter(a => a.quiz_concluido).length;
  topoEl.innerHTML = concluidas === aulas.length
    ? `🏆 Todas as ${aulas.length} matérias concluídas hoje!`
    : `🏆 ${concluidas} de ${aulas.length} matéri${aulas.length !== 1 ? 'as' : 'a'} concluída${concluidas !== 1 ? 's' : ''} hoje`;

  cardsEl.innerHTML = aulas.map(a => {
    const emoji = emojiMateria(a.materia);
    const concluido = a.quiz_concluido;
    const statusHtml = concluido
      ? `<span style="color:#27AE60;font-weight:700">✅ Concluído</span>`
      : `<span style="color:#F5A623;font-weight:700">⏳ Quiz pendente</span>`;
    const capituloHtml = a.capitulo
      ? `<div style="font-size:12px;color:#666;margin-bottom:8px">📖 ${a.capitulo}</div>` : '';
    return `
      <div style="background:white;border-radius:16px;padding:18px;margin-bottom:12px;box-shadow:0 2px 12px rgba(0,0,0,0.07);${concluido ? 'opacity:0.7' : ''}">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <div style="font-size:15px;font-weight:800">${emoji} ${a.materia}${a.capitulo ? ' — ' + a.capitulo : ''}</div>
          ${statusHtml}
        </div>
        <div style="font-size:12px;color:#888;margin-bottom:10px">${a.total_perguntas} perguntas geradas • ${a.trimestre}</div>
        <div style="display:flex;gap:8px">
          <button class="btn-secondary" style="flex:1;font-size:13px;padding:10px" onclick="verResumoAula(${a.id})">📖 Ver Resumo</button>
          <button class="btn-primary" style="flex:1;font-size:13px;padding:10px${concluido ? ';background:#27AE60' : ''}" onclick="abrirQuizDia(${a.id})">
            ${concluido ? '🔁 Refazer Quiz' : '⚡ Fazer Quiz'}
          </button>
        </div>
      </div>`;
  }).join('');
}

async function verResumoAula(aulaId) {
  const data = await get(`/api/aulas/${aulaId}`);
  const aula = data.aula;
  document.getElementById('modal-resumo').innerHTML = formatarTexto(aula.resumo || 'Resumo não disponível.');
  document.getElementById('modal-sucesso').classList.remove('hidden');
  document.getElementById('modal-overlay').classList.remove('hidden');
}

// Estado do quiz do dia
let quizDiaData = null;

async function abrirQuizDia(aulaId) {
  const data = await get(`/api/quiz/dia?aula_id=${aulaId}`);
  if (!data.perguntas || data.perguntas.length === 0) {
    alert('Nenhuma pergunta disponível para esta aula.');
    return;
  }
  quizDiaData = data;

  // Mostrar tela de resumo
  showTab('quiz');
  document.getElementById('quiz-selector').classList.add('hidden');
  document.getElementById('quiz-resumo-tela').classList.remove('hidden');
  document.getElementById('quiz-game').classList.add('hidden');
  document.getElementById('quiz-resultado').classList.add('hidden');

  const aula = data.aula;
  document.getElementById('quiz-resumo-materia-badge').textContent = aula.materia || '';
  document.getElementById('quiz-resumo-capitulo').textContent = aula.capitulo || '';
  document.getElementById('quiz-resumo-texto').innerHTML = formatarTexto(aula.resumo || '');
}

function iniciarQuizDoDia() {
  if (!quizDiaData) return;

  state.quiz = {
    perguntas: quizDiaData.perguntas,
    atual: 0, certas: 0, erradas: 0,
    erradasDetalhes: [], ativa: true,
    origemDia: true
  };

  document.getElementById('quiz-resumo-tela').classList.add('hidden');
  document.getElementById('quiz-game').classList.remove('hidden');
  renderPergunta();
}

function voltarPainelDia() {
  document.getElementById('quiz-resultado').classList.add('hidden');
  document.getElementById('quiz-selector').classList.remove('hidden');
  showTab('hoje');
}

// ─── Revisão da Semana ────────────────────────────────────────────────────────

async function carregarRevisaoSemana() {
  const el = document.getElementById('revisao-semana-lista');
  if (!el) return;
  el.innerHTML = '<div style="text-align:center;padding:12px;color:#999">Carregando...</div>';

  const data = await get('/api/quiz/semana');
  const materias = data.materias || [];

  if (materias.length === 0) {
    celebrarSemanaZerada();
    el.innerHTML = '';
    return;
  }

  el.innerHTML = materias.map(m => `
    <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid #f0f0f0">
      <div>
        <span style="font-size:14px">${emojiMateria(m.materia)} <strong>${m.materia}</strong></span>
        <span style="font-size:12px;color:#666;margin-left:8px">${m.total} questão${m.total !== 1 ? 'ões' : ''} pendente${m.total !== 1 ? 's' : ''}</span>
      </div>
      <button class="btn-primary" style="font-size:12px;padding:8px 14px" onclick="iniciarRevisaoMateria(${JSON.stringify(m.perguntas).replace(/"/g,'&quot;')})">Revisar</button>
    </div>
  `).join('');
}

function iniciarRevisaoMateria(perguntas) {
  if (!perguntas || perguntas.length === 0) return;

  state.quiz = {
    perguntas,
    atual: 0, certas: 0, erradas: 0,
    erradasDetalhes: [], ativa: true,
    origemDia: false
  };

  document.getElementById('quiz-selector').classList.add('hidden');
  document.getElementById('quiz-resumo-tela').classList.add('hidden');
  document.getElementById('quiz-resultado').classList.add('hidden');
  document.getElementById('quiz-game').classList.remove('hidden');
  renderPergunta();
}

// ─── Celebração Semana Zerada ────────────────────────────────────────────────

function celebrarSemanaZerada() {
  const nome = USUARIO.charAt(0).toUpperCase() + USUARIO.slice(1);
  const isTiago = USUARIO === 'tiago';

  // Mensagem personalizada
  const msg = isTiago
    ? { titulo: '🏆 SEMANA ZERADA!', sub: 'Você revisou TUDO essa semana!', detalhe: 'Isso é coisa de campeão! 🔵⚫⚪🔥', xp: '+100 XP — Semana Perfeita!' }
    : { titulo: '🏆 SEMANA ZERADA!', sub: 'Você revisou TUDO essa semana!', detalhe: 'Excelente disciplina, campeão! Continue assim! ⚽🔥', xp: '+100 XP — Semana Perfeita!' };

  // Modal de celebração
  const overlay = document.createElement('div');
  overlay.id = 'celebracao-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center;animation:fadeIn 0.3s ease';
  overlay.innerHTML = `
    <div style="background:white;border-radius:24px;padding:36px 28px;max-width:340px;width:90%;text-align:center;position:relative;overflow:hidden">
      <div id="confete-container" style="position:absolute;inset:0;pointer-events:none;overflow:hidden"></div>
      <div style="font-size:64px;margin-bottom:8px;animation:bounce 0.6s ease infinite alternate">🏆</div>
      <div style="font-size:22px;font-weight:900;color:#003DA5;margin-bottom:6px">${msg.titulo}</div>
      <div style="font-size:16px;font-weight:700;margin-bottom:8px">${nome}, ${msg.sub}</div>
      <div style="font-size:13px;color:#555;margin-bottom:20px">${msg.detalhe}</div>
      <div style="background:linear-gradient(135deg,#F5A623,#FF6B35);color:white;border-radius:12px;padding:12px;font-size:15px;font-weight:800;margin-bottom:20px;animation:pulse 1s ease infinite">
        ${msg.xp}
      </div>
      <button onclick="document.getElementById('celebracao-overlay').remove()" style="background:#003DA5;color:white;border:none;border-radius:12px;padding:14px 32px;font-size:15px;font-weight:700;cursor:pointer;width:100%">
        ⚽ Continuar jogando!
      </button>
    </div>
  `;
  document.body.appendChild(overlay);

  // Confete
  const container = document.getElementById('confete-container');
  const cores = ['#003DA5','#F5A623','#27AE60','#E74C3C','#9B59B6','#3498DB'];
  for (let i = 0; i < 60; i++) {
    const c = document.createElement('div');
    const cor = cores[Math.floor(Math.random() * cores.length)];
    const left = Math.random() * 100;
    const delay = Math.random() * 2;
    const dur = 2 + Math.random() * 2;
    const size = 6 + Math.random() * 8;
    c.style.cssText = `position:absolute;width:${size}px;height:${size}px;background:${cor};border-radius:${Math.random() > 0.5 ? '50%' : '2px'};left:${left}%;top:-10px;animation:cair ${dur}s ${delay}s ease-in forwards`;
    container.appendChild(c);
  }

  // Fechar ao clicar fora
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
}

// ─── Mapa de Dificuldades (aluno) ────────────────────────────────────────────

async function carregarDificuldades() {
  const el = document.getElementById('dificuldades-lista');
  if (!el) return;

  const data = await get('/api/dificuldades');
  const difs = data.dificuldades || [];

  if (difs.length === 0) {
    el.innerHTML = '<div style="text-align:center;color:#27AE60;font-size:13px;padding:8px">✅ Nenhuma dificuldade registrada ainda!</div>';
    return;
  }

  // Agrupar por matéria
  const porMateria = {};
  difs.forEach(d => {
    if (!porMateria[d.materia]) porMateria[d.materia] = [];
    porMateria[d.materia].push(d);
  });

  el.innerHTML = Object.entries(porMateria).map(([materia, items]) => `
    <div style="margin-bottom:12px">
      <div style="font-weight:700;font-size:13px;margin-bottom:6px">${emojiMateria(materia)} ${materia}</div>
      ${items.map(d => `
        <div style="display:flex;justify-content:space-between;align-items:center;font-size:12px;padding:6px 0;border-bottom:1px solid #f5f5f5;color:#444">
          <span>${d.tema || 'Sem tema'}</span>
          <span style="color:#E74C3C;font-weight:700">${d.total_erros} erro${d.total_erros !== 1 ? 's' : ''}</span>
        </div>
      `).join('')}
    </div>
  `).join('');
}
