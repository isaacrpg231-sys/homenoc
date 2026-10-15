/* HomeNOC: inicialização da interface. Rotas (#painel, #mapa, ...), menu,
   leitura do estado a cada poucos segundos, tema, login e avisos no topo. */
"use strict";
(function (HN) {
  const { fmt } = HN;
  const { html, cru, pintar, icone, toast } = HN.ui;

  const ROTAS = [
    ["painel", "Painel"], ["mapa", "Mapa"], ["aparelhos", "Aparelhos"],
    ["trafego", "Tráfego"], ["eventos", "Eventos"], ["ajustes", "Ajustes"],
  ];
  const $ = (id) => document.getElementById(id);

  let rotaAtual = null, visaoAtual = null, temporizador = null, falhas = 0, parado = false, lendo = false, deNovo = false;

  // ------------------------------------------------------------------ tema
  const temaDoHost = document.documentElement.dataset.theme || null;   // quem incorpora a página pode já ter escolhido
  function aplicarTema(tema) {
    const raiz = document.documentElement;
    if (tema === "light" || tema === "dark") raiz.dataset.theme = tema;
    else if (temaDoHost) raiz.dataset.theme = temaDoHost;
    else delete raiz.dataset.theme;
    document.querySelectorAll("[data-tema]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tema === (tema || "auto"))));
  }

  // ------------------------------------------------------------------ menu
  function montarMenu() {
    const itens = (classe) => ROTAS.map(([id, nome]) => html`<a href="#${id}" data-rota="${id}" class="${classe}">${icone(id)}<span>${nome}</span><span class="contador" data-contador="${id}" hidden></span></a>`);
    pintar($("nav"), itens(""));
    pintar($("abas"), itens(""));
  }

  function marcarMenu(rota) {
    document.querySelectorAll("[data-rota]").forEach((a) => {
      if (a.dataset.rota === rota) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
  }

  // ------------------------------------------------------------------ rotas
  function lerRota() {
    const [rota, sub] = decodeURIComponent(location.hash.replace(/^#/, "")).split("/");
    return { rota: ROTAS.some((r) => r[0] === rota) ? rota : "painel", sub: sub || null };
  }

  function rotear() {
    const { rota, sub } = lerRota();
    if (HN.gaveta.aberta) HN.gaveta.fechar(true);
    if (rota === rotaAtual && visaoAtual) {
      if (sub && visaoAtual.focar) visaoAtual.focar(sub);
      return;
    }
    if (visaoAtual && visaoAtual.desmontar) visaoAtual.desmontar();
    rotaAtual = rota;
    visaoAtual = HN.visoes[rota];
    HN.visaoAtual = visaoAtual;
    const el = document.createElement("div");
    const estreita = rota === "ajustes" || rota === "eventos";       // texto e formulários: colunas mais curtas
    el.className = estreita ? "visao estreita" : "visao";
    el.dataset.visao = rota;
    $("faixas").classList.toggle("estreita", estreita);
    $("visao").replaceChildren(el);
    marcarMenu(rota);
    atualizarTitulo();
    window.scrollTo(0, 0);
    $("conteudo").focus({ preventScroll: true });
    visaoAtual.montar(el, HN.S.estado, sub);
  }

  function problemas(estado) {
    if (!estado) return 0;
    const fora = (estado.dispositivos || []).filter((d) => d.alertar && !d.este_pc && !d.online).length;
    return fora + (estado.internet && estado.internet.online === false ? 1 : 0);
  }

  function atualizarTitulo() {
    const n = problemas(HN.S.estado);
    const nome = (ROTAS.find((r) => r[0] === rotaAtual) || ROTAS[0])[1];
    document.title = `${n ? `(${n}) ` : ""}${nome} – HomeNOC${HN.DEMO ? " (demonstração)" : ""}`;
  }

  // ------------------------------------------------------------------ leitura periódica
  async function ler() {
    if (parado) return;
    if (lendo) { deNovo = true; return; }          // pediram uma leitura no meio de outra: faz logo depois
    lendo = true;
    deNovo = false;
    clearTimeout(temporizador);
    try {
      const estado = await HN.api("GET", "/api/estado");
      falhas = 0;
      HN.S.estado = estado;
      aplicar(estado);
    } catch (e) {
      if (e.status === 401 || parado) { lendo = false; return; }
      falhas += 1;
      if (falhas >= 2) faixaErro(e.message);
    }
    lendo = false;
    if (parado) return;
    const ativa = HN.S.estado && HN.S.estado.varredura && HN.S.estado.varredura.ativa;
    temporizador = setTimeout(ler, deNovo ? 100 : document.hidden ? 20000 : ativa ? 1500 : 4000);
  }

  function aplicar(estado) {
    faixaErro(null);
    const n = problemas(estado);
    document.querySelectorAll("[data-contador=painel]").forEach((c) => {
      c.hidden = !n || rotaAtual === "painel";
      c.textContent = n;
      c.setAttribute("aria-label", `${n} ${n === 1 ? "problema" : "problemas"}`);
    });
    atualizarTitulo();
    pintarVarredura(estado);
    if (visaoAtual && visaoAtual.atualizar) visaoAtual.atualizar(estado);
    HN.gaveta.atualizar(estado);
  }

  function pintarVarredura(estado) {
    const v = estado.varredura || {};
    let conteudo;
    if (v.ativa) conteudo = html`<b>Varrendo a rede</b> ${v.etapa || ""}<div class="barra" role="progressbar" aria-label="Progresso da varredura" aria-valuenow="${v.progresso || 0}" aria-valuemin="0" aria-valuemax="100"><i style="width:${v.progresso || 0}%"></i></div>`;
    else if (v.erro) conteudo = html`<b>A varredura falhou</b> ${v.erro}`;
    else if (v.ultima) conteudo = html`Varredura ${fmt.ha(v.ultima, estado.agora)}${v.proxima ? html`<br>próxima em <b>${fmt.duracao(Math.max(60, v.proxima - estado.agora))}</b>` : ""}`;
    else conteudo = html`Preparando a primeira varredura`;
    pintar($("varredura-rail"), conteudo);
    pintar($("varredura-topo"), v.ativa ? html`<b>Varrendo</b> ${v.progresso || 0}%` : v.ultima ? html`Varrido ${fmt.ha(v.ultima, estado.agora)}` : "");
  }

  // ------------------------------------------------------------------ faixas no topo
  let erroAtual = null;
  function faixaErro(mensagem) {
    if (mensagem === erroAtual) return;
    erroAtual = mensagem;
    pintarFaixas();
  }

  function urlRepositorio() {
    const m = location.hostname.match(/^([\w-]+)\.github\.io$/i);
    const repo = location.pathname.split("/").filter(Boolean)[0];
    return m && repo ? `https://github.com/${m[1]}/${repo}` : null;
  }

  function pintarFaixas() {
    const partes = [];
    if (erroAtual) partes.push(html`<div class="faixa erro" role="alert"><span>${erroAtual}</span><button type="button" class="botao pequeno" data-acao="reconectar">Tentar de novo</button></div>`);
    if (HN.DEMO) {
      const repo = urlRepositorio();
      partes.push(html`<div class="faixa demo"><span><b>Demonstração</b> com uma rede simulada e dados fictícios.<span class="so-largo"> Simule uma queda e veja o painel reagir.</span></span>
        <button type="button" class="botao pequeno" data-acao="simular-internet">Simular queda da internet</button>
        <button type="button" class="botao pequeno" data-acao="simular-novo">Simular aparelho novo</button>
        ${repo ? html`<a class="botao pequeno" href="${repo}" target="_blank" rel="noopener noreferrer">${icone("abrir")}Código no GitHub</a>` : ""}</div>`);
    }
    $("faixas").hidden = !partes.length;
    pintar($("faixas"), partes);
  }

  // ------------------------------------------------------------------ login
  function mostrarEntrada(sessao, erroAcesso) {
    parado = true;
    clearTimeout(temporizador);
    $("app").hidden = true;
    const el = $("entrada");
    el.hidden = false;
    if (erroAcesso) {
      pintar(el, html`<div class="bloco entrada-caixa"><h1>HomeNOC</h1><p>${erroAcesso}</p>
        <p class="dica">No computador onde o HomeNOC roda, abra Ajustes e ligue “Permitir abrir o HomeNOC pelo celular”.</p>
        <button type="button" class="botao" data-acao="recarregar">Tentar de novo</button></div>`, true);
      return;
    }
    pintar(el, html`<form class="bloco entrada-caixa" data-form="entrar" novalidate>
      <h1>${cru('<svg class="marca-entrada" viewBox="0 0 32 32" aria-hidden="true"><rect x="2" y="7" width="28" height="18" rx="4" fill="#172028"/><rect x="7" y="13" width="7" height="6" rx="1" fill="#05080A"/><rect x="18" y="13" width="7" height="6" rx="1" fill="#05080A"/><circle cx="8.6" cy="11" r="1.4" fill="#0CA30C"/><circle cx="19.6" cy="11" r="1.4" fill="#0CA30C"/></svg>')}HomeNOC</h1>
      <p class="discreto">Digite a senha definida no computador do HomeNOC.</p>
      <label class="campo"><span>Senha</span><input type="password" name="senha" autocomplete="current-password" required autofocus></label>
      <div class="resultado" data-parte="erro" hidden></div>
      <button type="submit" class="botao primario">Entrar</button>
    </form>`, true);
    const campo = el.querySelector("input[name=senha]");
    if (campo) campo.focus();
  }

  function ligarEntrada() {
    $("entrada").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const form = ev.target;
      const botao = form.querySelector("button[type=submit]");
      try {
        await HN.ui.ocupado(botao, "Entrando…", () => HN.api("POST", "/api/login", { senha: form.elements.senha.value }));
        $("entrada").hidden = true;
        iniciarApp();
      } catch (e) {
        HN.ui.resultado(form.querySelector("[data-parte=erro]"), false, e.message);
        form.elements.senha.select();
      }
    });
    $("entrada").addEventListener("click", (ev) => {
      if (ev.target.closest("[data-acao=recarregar]")) location.reload();
    });
  }

  // ------------------------------------------------------------------ início
  function iniciarApp() {
    parado = false;
    $("entrada").hidden = true;
    $("app").hidden = false;
    pintarFaixas();
    if (!rotaAtual) rotear();
    ler();
  }

  async function iniciar() {
    aplicarTema(HN.ui.ler("tema", "auto"));
    montarMenu();
    ligarEntrada();
    HN.gaveta.ligar();
    HN.aoPerderSessao = () => mostrarEntrada();
    if (HN.DEMO) HN.demo.iniciar();

    document.querySelectorAll("[data-tema]").forEach((b) => b.addEventListener("click", () => {
      HN.ui.gravar("tema", b.dataset.tema);
      aplicarTema(b.dataset.tema);
    }));
    window.addEventListener("hashchange", rotear);
    $("pular").addEventListener("click", () => $("conteudo").focus());
    document.addEventListener("visibilitychange", () => { if (!document.hidden && !parado) ler(); });
    let espera = null;
    window.addEventListener("resize", () => {
      clearTimeout(espera);
      espera = setTimeout(() => { if (visaoAtual && visaoAtual.redesenhar) visaoAtual.redesenhar(); }, 220);
    });
    $("faixas").addEventListener("click", async (ev) => {
      const b = ev.target.closest("[data-acao]");
      if (!b) return;
      if (b.dataset.acao === "reconectar") { falhas = 0; ler(); }
      if (b.dataset.acao === "simular-internet") { const s = HN.demo.simularQuedaInternet(); toast(`A internet vai cair por ${s} segundos. Veja o painel e os eventos.`); ler(); }
      if (b.dataset.acao === "simular-novo") { const d = HN.demo.simularAparelhoNovo(); toast(d ? `${d.nome} entrou na rede.` : "Todos os aparelhos simulados já entraram."); ler(); }
    });

    try {
      const sessao = await HN.api("GET", "/api/sessao");
      if (!sessao.autenticado) return mostrarEntrada(sessao);
    } catch (e) {
      if (e.status === 403) return mostrarEntrada(null, e.message);
      $("app").hidden = false;
      faixaErro(e.message);
      rotear();
      setTimeout(ler, 4000);
      return;
    }
    iniciarApp();
  }

  HN.app = {
    atualizarJa() { setTimeout(ler, 150); },
    encerrado() {
      parado = true;
      clearTimeout(temporizador);
      $("app").hidden = true;
      $("entrada").hidden = false;
      pintar($("entrada"), html`<div class="bloco entrada-caixa"><h1>HomeNOC encerrado</h1>
        <p>O monitoramento parou. Para abrir de novo, use o atalho do HomeNOC ou o arquivo <code>iniciar.bat</code>.</p></div>`, true);
    },
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})(window.HN = window.HN || {});
