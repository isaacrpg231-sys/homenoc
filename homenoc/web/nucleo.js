/* HomeNOC: peças compartilhadas pela interface.
   - api(): conversa com o servidor (ou com a demonstração);
   - html``: monta HTML escapando tudo que vem de fora (nome de aparelho,
     anúncio UPnP e DNS podem ser escolhidos por qualquer um na rede);
   - ícones, avisos rápidos (toast) e pequenos utilitários. */
"use strict";
(function (HN) {
  const { fmt } = HN;
  const esc = fmt.esc;

  // ------------------------------------------------------------------ demonstração?
  const busca = new URLSearchParams(location.search);
  const DEMO = Boolean(window.HOMENOC_DEMO || busca.has("demo") || /\.github\.io$/i.test(location.hostname));

  // ------------------------------------------------------------------ HTML seguro
  class Cru {
    constructor(s) { this.s = String(s); }
    toString() { return this.s; }
  }
  const cru = (s) => new Cru(s);
  function valorHtml(v) {
    if (v == null || v === false) return "";
    if (v instanceof Cru) return v.s;
    if (Array.isArray(v)) return v.map(valorHtml).join("");
    return esc(v);
  }
  function html(partes, ...valores) {
    let s = partes[0];
    valores.forEach((v, i) => { s += valorHtml(v) + partes[i + 1]; });
    return cru(s);
  }
  /* Troca o conteúdo só se ele mudou: assim a atualização a cada poucos segundos
     não tira o foco do teclado nem reinicia animações à toa. */
  function pintar(el, conteudo, forcar) {
    if (!el) return el;
    const s = valorHtml(conteudo);
    if (forcar || el._pintado !== s) {
      el.innerHTML = s;
      el._pintado = s;
    }
    return el;
  }
  const NUM = [0, 1, 2].map((c) => new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 0, maximumFractionDigits: c }));
  const num = (v, casas = 0) => (v == null || Number.isNaN(v) ? "–" : NUM[Math.max(0, Math.min(2, casas))].format(v));
  /* Rótulos do eixo em Mbps: mais casas quando os valores são pequenos. */
  const eixoMbps = (v, maximo) => num(v, maximo >= 10 ? 0 : maximo >= 1 ? 1 : 2);

  // ------------------------------------------------------------------ API
  class ErroApi extends Error {
    constructor(status, mensagem, dados) {
      super(mensagem);
      this.status = status;
      this.dados = dados;
    }
  }

  async function api(metodo, caminho, corpo) {
    if (DEMO) return HN.demo.api(metodo, caminho, corpo);
    const opcoes = { method: metodo, headers: { "X-HomeNOC": "1", Accept: "application/json" }, credentials: "same-origin", cache: "no-store" };
    if (corpo !== undefined) {
      opcoes.headers["Content-Type"] = "application/json";
      opcoes.body = JSON.stringify(corpo);
    }
    let resposta;
    try {
      resposta = await fetch(caminho, opcoes);
    } catch (e) {
      throw new ErroApi(0, "Sem conexão com o HomeNOC. Ele ainda está aberto no computador?");
    }
    let dados = null;
    try { dados = await resposta.json(); } catch (e) { /* resposta sem JSON */ }
    if (!resposta.ok) {
      const mensagem = (dados && dados.erro) || `O HomeNOC respondeu com erro ${resposta.status}.`;
      if (resposta.status === 401 && caminho !== "/api/login" && HN.aoPerderSessao) HN.aoPerderSessao();
      throw new ErroApi(resposta.status, mensagem, dados);
    }
    return dados;
  }

  // ------------------------------------------------------------------ ícones (traço, 24x24)
  const ICONES = {
    painel: '<path d="M3 13h4l2.5-6 3.5 11 3-8 1.5 3H21"/>',
    mapa: '<circle cx="12" cy="5" r="2.3"/><circle cx="5" cy="18.5" r="2.3"/><circle cx="19" cy="18.5" r="2.3"/><path d="M12 7.3v4.2M12 11.5l-5.4 5.2M12 11.5l5.4 5.2"/>',
    aparelhos: '<rect x="2.5" y="4" width="13.5" height="10" rx="1.5"/><path d="M6.5 18h5.5M9.2 14v4"/><rect x="17.5" y="8" width="4" height="11.5" rx="1"/>',
    trafego: '<path d="M8 4v15.5M4 15.5l4 4 4-4M16 20V4.5M12 8.5l4-4 4 4"/>',
    eventos: '<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15z"/><path d="M10 21a2.1 2.1 0 0 0 4 0"/>',
    ajustes: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2.2"/><circle cx="9" cy="17" r="2.2"/>',
    varrer: '<path d="M20 12a8 8 0 1 1-2.4-5.7M20 4.5V9h-4.5"/>',
    fechar: '<path d="M6 6l12 12M18 6 6 18"/>',
    baixar: '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 20h14"/>',
    abrir: '<path d="M14 4.5h5.5V10M19.5 4.5 11 13M17 14v5.5H4.5V7H10"/>',
    centralizar: '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/><circle cx="12" cy="12" r="2.5"/>',
    copiar: '<rect x="8.5" y="8.5" width="11" height="11" rx="1.5"/><path d="M15.5 8.5V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v9.5a1 1 0 0 0 1 1h3.5"/>',
  };
  const icone = (nome) => cru(`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONES[nome] || ""}</svg>`);
  const glifo = (tipo) => cru(HN.mapa.glifo(tipo));

  // ------------------------------------------------------------------ aparelhos
  function situacao(d) {
    if (d.online) return { estado: "ok", texto: "Na rede" };
    if (d.alertar) return { estado: "critico", texto: "Sem resposta" };
    return { estado: "off", texto: "Fora da rede" };
  }
  const roteadorDe = (estado) => {
    const lista = (estado && estado.dispositivos) || [];
    const gw = estado && estado.rede && estado.rede.gateway;
    return lista.find((d) => d.ip && d.ip === gw) || lista.find((d) => d.tipo === "roteador") || null;
  };
  const dispositivo = (id) => ((HN.S.estado && HN.S.estado.dispositivos) || []).find((d) => d.id === id) || null;
  const nomePorta = (porta) => {
    const conhecidas = (HN.S.estado && HN.S.estado.portas_conhecidas) || {};
    return conhecidas[String(porta)] || "";
  };
  /* "Novo" = apareceu nos últimos 7 dias e não estava na primeira varredura. */
  let inicio = { estado: null, ts: 0 };
  function inicioInventario() {
    const e = HN.S.estado;
    if (inicio.estado !== e) {
      const ts = ((e && e.dispositivos) || []).map((d) => d.primeira_vez).filter(Boolean);
      inicio = { estado: e, ts: ts.length ? Math.min(...ts) : 0 };
    }
    return inicio.ts;
  }
  const novo = (d, agora) => Boolean(d.primeira_vez && agora - d.primeira_vez < 7 * 86400 && d.primeira_vez - inicioInventario() > 900);

  // ------------------------------------------------------------------ pedaços de interface
  function alternar({ nome, marcado, titulo, descricao, desativado, rotulo }) {
    return html`<label class="alternar"><input type="checkbox" name="${nome}" ${marcado ? cru("checked") : ""} ${desativado ? cru("disabled") : ""} ${rotulo ? cru(`aria-label="${esc(rotulo)}"`) : ""}><span class="trilho" aria-hidden="true"></span>${titulo ? html`<span class="texto"><b>${titulo}</b>${descricao ? html`<small>${descricao}</small>` : ""}</span>` : ""}</label>`;
  }

  /* Repinta uma lista sem perder o foco do teclado (linha ou caixa de seleção). */
  function preservarFoco(container, pintura) {
    const ativo = document.activeElement;
    let lugar = null;
    if (ativo && container && container.contains(ativo)) {
      const linha = ativo.closest("[data-id]");
      if (linha) lugar = { id: linha.dataset.id, nome: ativo === linha ? null : ativo.getAttribute("name") };
    }
    pintura();
    if (!lugar) return;
    const linha = [...container.querySelectorAll("[data-id]")].find((x) => x.dataset.id === lugar.id);
    const alvo = linha && (lugar.nome ? linha.querySelector(`[name="${lugar.nome}"]`) : linha);
    if (alvo && alvo !== document.activeElement) alvo.focus({ preventScroll: true });
  }

  function vazio(titulo, texto) {
    return html`<div class="vazio"><b>${titulo}</b>${texto || ""}</div>`;
  }

  let temporizadorToast = null;
  function toast(mensagem, ms = 3200) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = mensagem;
    el.hidden = false;
    clearTimeout(temporizadorToast);
    temporizadorToast = setTimeout(() => { el.hidden = true; }, ms);
  }

  /* Mostra "carregando" num botão enquanto uma ação roda e devolve o resultado. */
  async function ocupado(botao, texto, acao) {
    const original = botao ? botao.innerHTML : "";
    if (botao) {
      botao.disabled = true;
      if (texto) botao.textContent = texto;
    }
    try {
      return await acao();
    } finally {
      if (botao) {
        botao.disabled = false;
        botao.innerHTML = original;
      }
    }
  }

  function resultado(el, ok, conteudo) {
    if (!el) return;
    el.hidden = false;
    el.className = "resultado";
    el.dataset.ok = String(Boolean(ok));
    pintar(el, conteudo);
  }

  /* Valores de um formulário como objeto aninhado: name="alertas.telegram.token". */
  function lerFormulario(form) {
    const saida = {};
    form.querySelectorAll("input[name], select[name], textarea[name]").forEach((campo) => {
      if (campo.disabled || campo.dataset.ignorar !== undefined) return;
      let valor;
      if (campo.type === "checkbox") valor = campo.checked;
      else if (campo.type === "number") valor = campo.value === "" ? null : Number(campo.value);
      else if (campo.dataset.lista !== undefined) valor = campo.value.split(/[\s,;]+/).filter(Boolean);
      else valor = campo.value;
      const partes = campo.name.split(".");
      let alvo = saida;
      partes.slice(0, -1).forEach((p) => { alvo = alvo[p] = alvo[p] || {}; });
      alvo[partes[partes.length - 1]] = valor;
    });
    return saida;
  }

  function baixarArquivo(nome, conteudo, tipo) {
    const url = URL.createObjectURL(new Blob([conteudo], { type: tipo }));
    const a = document.createElement("a");
    a.href = url;
    a.download = nome;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  function exportarCsv() {
    if (window.HOMENOC_ARTEFATO) toast("Nesta página de demonstração o download é bloqueado. No HomeNOC instalado, o CSV baixa na hora.", 5000);
    else if (DEMO) baixarArquivo("homenoc-aparelhos.csv", "﻿" + HN.demo.csv(), "text/csv;charset=utf-8");
    else location.href = "/api/dispositivos.csv";
  }

  const ler = (chave, padrao) => { try { const v = localStorage.getItem(`homenoc.${chave}`); return v == null ? padrao : v; } catch (e) { return padrao; } };
  const gravar = (chave, valor) => { try { localStorage.setItem(`homenoc.${chave}`, valor); } catch (e) { /* navegador sem armazenamento */ } };

  HN.S = HN.S || { estado: null };
  HN.DEMO = DEMO;
  HN.ErroApi = ErroApi;
  HN.api = api;
  HN.ui = {
    html, cru, pintar, esc, num, eixoMbps, icone, glifo, situacao, roteadorDe, dispositivo, nomePorta, novo, alternar, vazio, preservarFoco,
    toast, ocupado, resultado, lerFormulario, baixarArquivo, exportarCsv, ler, gravar,
  };
  HN.visoes = HN.visoes || {};
})(window.HN = window.HN || {});
