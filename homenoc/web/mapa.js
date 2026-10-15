/* HomeNOC: mapa da rede no estilo do Zenmap. O roteador fica no centro, cada
   aparelho preso a ele por uma "mola" cujo comprimento cresce com a latência, e o
   caminho até a internet sai do roteador (para a direita na tela larga, para cima
   no celular). Arrastar, aproximar (roda, pinça ou botões) e clicar. */
"use strict";
(function (HN) {
  const NS = "http://www.w3.org/2000/svg";
  // Ícones em traço simples, desenhados num quadrado 24x24 centrado em 0,0
  const GLIFOS = {
    roteador: "M-8 3h16v5h-16zM-5 3l-2-8M5 3l2-8M-4 5.5h1M0 5.5h1",
    este_pc: "M-9-6h18v11h-18zM-4 9h8M0 5v4",
    computador: "M-9-6h18v11h-18zM-4 9h8M0 5v4",
    celular: "M-5-9h10v18h-10zM-1 6h2",
    tv: "M-10-6h20v12h-20zM-4 9h8",
    impressora: "M-6-9h12v5h-12zM-9-4h18v8h-18zM-6 2h12v7h-12z",
    camera: "M-9-4h12v8h-12zM3-1l6-3v8l-6-3",
    iot: "M-6-6h12v12h-12zM-2-2h4v4h-4zM-9-3h3M-9 3h3M6-3h3M6 3h3",
    servidor: "M-7-9h14v6h-14zM-7-2h14v6h-14zM-7 5h14v4h-14z",
    desconhecido: "M-3-4a3 3 0 1 1 4 3c-1 .5-1 1.2-1 2.5M0 6v.5",
    internet: "M-10 4a5 5 0 0 1 2-9 7 7 0 0 1 13 1 4 4 0 0 1 3 8z",
    salto: "M-6 0h12M2-4l4 4-4 4",
  };
  const glifo = (tipo) => `<svg viewBox="-12 -12 24 24" aria-hidden="true"><path d="${GLIFOS[tipo] || GLIFOS.desconhecido}"/></svg>`;
  const privado = (ip) => /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(ip || "");
  const cgnat = (ip) => /^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(ip || "");
  const NOVO_MS = 8000;
  const calmo = () => window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

  function papelSalto(ip) {
    if (!ip) return "Sem resposta";
    if (privado(ip)) return "Modem/ONT ou 2º roteador";
    if (cgnat(ip)) return "CGNAT da operadora";
    return "Rede da operadora";
  }

  function criar(container, opcoes = {}) {
    container.innerHTML = `<svg class="mapa" role="group" aria-label="Mapa da rede: use Tab para passar pelos aparelhos e Enter para ver detalhes"><g class="cena"><g class="arestas"></g><g class="nos"></g></g></svg>`;
    const svg = container.querySelector("svg");
    const cena = svg.querySelector(".cena"), gA = svg.querySelector(".arestas"), gN = svg.querySelector(".nos");
    const pos = HN._posicoesMapa || (HN._posicoesMapa = new Map());   // posições sobrevivem à troca de tela
    let nos = [], arestas = [], centro = null, alpha = 0, vista = { x: 0, y: 0, k: 1 };
    let selecionado = null, filtro = "", mostrarOff = true, sujo = true, mexeuNaVista = false, vivo = true, enquadrado = false;
    let ultimoEstado = null;

    function el(tag, attrs, pai) {
      const e = document.createElementNS(NS, tag);
      for (const k in attrs) e.setAttribute(k, attrs[k]);
      if (pai) pai.appendChild(e);
      return e;
    }
    const deitado = () => svg.clientWidth > svg.clientHeight * 1.15;   // tela larga: internet para a direita

    // ----------------------------------------------------------- grafo
    function montar(estado) {
      if (!estado) return;
      const primeiraVez = !ultimoEstado;
      ultimoEstado = estado;
      const rede = estado.rede || {};
      const lista = (estado.dispositivos || []).filter((d) => mostrarOff || d.online);
      const gw = lista.find((d) => d.ip && d.ip === rede.gateway) || lista.find((d) => d.tipo === "roteador");
      const meu = lista.find((d) => d.este_pc);
      centro = gw ? gw.id : meu ? meu.id : (lista[0] && lista[0].id);
      const novos = lista.map((d) => ({ id: d.id, tipo: d.tipo, d }));
      const novasArestas = lista.filter((d) => d.id !== centro).map((d) => ({ a: centro, b: d.id, offline: !d.online }));
      let anterior = centro;
      const saltos = (estado.caminho || []).filter((s) => s.salto > 1 && s.ip !== rede.gateway);
      saltos.forEach((s) => {
        const id = `salto-${s.salto}`;
        const final = s.ip && (s.ip === "8.8.8.8" || s.ip === "1.1.1.1");
        novos.push({ id, tipo: final ? "internet" : "salto", salto: s, papel: final ? "Internet" : papelSalto(s.ip) });
        if (anterior) novasArestas.push({ a: anterior, b: id, internet: true });
        anterior = id;
      });
      if (!novos.some((n) => n.tipo === "internet") && anterior) {
        novos.push({ id: "internet", tipo: "internet", papel: "Internet", internet: estado.internet });
        novasArestas.push({ a: anterior, b: "internet", internet: true });
      }
      const c = pos.get(centro) || { x: 0, y: 0 };
      const jaConhecidos = novos.every((n) => pos.has(n.id));       // voltou para o mapa: o desenho já está pronto
      novos.forEach((n, i) => {
        if (!pos.has(n.id)) {
          const ang = (i / Math.max(1, novos.length)) * Math.PI * 2;
          // Só pulsa quem chegou depois do mapa aberto (não tudo na primeira vez).
          pos.set(n.id, { x: c.x + Math.cos(ang) * 60, y: c.y + Math.sin(ang) * 60, vx: 0, vy: 0, fixo: false, nasceu: primeiraVez ? 0 : Date.now() });
        }
      });
      const cp = pos.get(centro);
      if (cp) { cp.x = 0; cp.y = 0; cp.fixo = true; }
      const mudou = novos.length !== nos.length || novos.some((n, i) => !nos[i] || nos[i].id !== n.id);
      nos = novos;
      arestas = novasArestas;
      if (mudou) { alpha = Math.max(alpha, primeiraVez ? (jaConhecidos ? 0.1 : 1) : 0.5); enquadrado = false; }
      sujo = true;
    }

    function comprimento(e) {
      if (e.internet) return e.a === centro && e.b === "internet" ? 170 : 85;   // sem caminho conhecido: só a nuvem
      const n = nos.find((x) => x.id === e.b);
      const lat = n && n.d && n.d.latencia != null ? n.d.latencia : 8;
      return 135 + Math.min(lat, 60) * 2.4;           // mais longe = mais lento
    }

    function passo() {
      if (alpha < 0.005) return;
      const P = (id) => pos.get(id);
      const largo = deitado();
      for (let i = 0; i < nos.length; i++) {
        for (let j = i + 1; j < nos.length; j++) {
          const a = P(nos[i].id), b = P(nos[j].id);
          let dx = b.x - a.x, dy = b.y - a.y;
          const d2 = dx * dx + dy * dy || 1, d = Math.sqrt(d2), f = (4300 / d2) * alpha;
          dx /= d; dy /= d;
          if (!a.fixo) { a.vx -= dx * f; a.vy -= dy * f; }
          if (!b.fixo) { b.vx += dx * f; b.vy += dy * f; }
        }
      }
      arestas.forEach((e) => {
        const a = P(e.a), b = P(e.b);
        if (!a || !b) return;
        let dx = b.x - a.x, dy = b.y - a.y;
        const d = Math.hypot(dx, dy) || 1, f = (d - comprimento(e)) * 0.04 * alpha;
        dx /= d; dy /= d;
        if (!a.fixo) { a.vx += dx * f; a.vy += dy * f; }
        if (!b.fixo) { b.vx -= dx * f; b.vy -= dy * f; }
        if (b.fixo) return;
        if (e.internet) { if (largo) b.vx += 1.6 * alpha; else b.vy -= 1.6 * alpha; }      // o caminho até a internet
        else if (largo) b.vx -= 0.55 * alpha; else b.vy += 0.4 * alpha;                    // a casa fica do outro lado
      });
      nos.forEach((n) => {
        const p = P(n.id);
        if (p.fixo) return;
        p.vx *= 0.82; p.vy *= 0.82; p.x += p.vx; p.y += p.vy;
      });
      alpha *= 0.985;
    }

    // ----------------------------------------------------------- desenho
    function rotulo(n) {
      if (n.tipo === "internet") return ["Internet", n.salto ? n.salto.ip : ""];
      if (n.tipo === "salto") return [n.papel, n.salto.ip || "*"];
      return [n.d.nome, n.d.ip || "IP desconhecido"];
    }

    function bate(n) {
      if (!filtro || !n.d) return true;
      const d = n.d;
      return [d.ip, d.nome, d.mac, d.fabricante, d.tipo_nome, d.nome_dns, d.upnp && d.upnp.modelo].join(" ").toLowerCase().includes(filtro);
    }

    const pulsando = (p) => p && p.nasceu && Date.now() - p.nasceu < NOVO_MS;

    function desenhar() {
      const ativo = document.activeElement;
      const focado = ativo && gN.contains(ativo) ? ativo.dataset.id : null;   // o teclado não perde o lugar
      gA.textContent = "";
      gN.textContent = "";
      arestas.forEach((e) => {
        const a = pos.get(e.a), b = pos.get(e.b);
        if (!a || !b) return;
        el("line", { class: `aresta${e.internet ? " internet" : ""}${e.offline ? " offline" : ""}`, x1: a.x, y1: a.y, x2: b.x, y2: b.y }, gA);
      });
      nos.forEach((n) => {
        const p = pos.get(n.id), d = n.d;
        const online = d ? d.online : n.tipo === "internet" ? !(ultimoEstado && ultimoEstado.internet && ultimoEstado.internet.online === false) : !!(n.salto && n.salto.ip);
        const problema = d ? ((d.zabbix && d.zabbix.problemas && d.zabbix.problemas.length) || (d.alertar && !d.online && !d.este_pc))
          : n.tipo === "internet" && !online;
        const [t1, t2] = rotulo(n);
        const g = el("g", {
          class: `no ${online ? "online" : "offline"}${problema ? " problema" : ""}${selecionado === n.id ? " selecionado" : ""}`,
          transform: `translate(${p.x.toFixed(1)},${p.y.toFixed(1)})`, tabindex: 0, role: "button",
          "aria-label": `${t1}, ${t2}${d ? (d.online ? ", na rede" : ", fora da rede") : ""}`,
        }, gN);
        g.dataset.id = n.id;
        g.style.opacity = bate(n) ? 1 : 0.16;
        const r = n.id === centro ? 25 : n.tipo === "internet" ? 23 : n.tipo === "salto" ? 14 : 19;
        if (pulsando(p)) {
          const f = calmo() ? 0.4 : ((Date.now() - p.nasceu) % 1400) / 1400;
          el("circle", { class: "onda", r: (r + 3 + 16 * f).toFixed(1), opacity: (1 - f).toFixed(2) }, g);
        }
        el("circle", { class: "halo", r }, g);
        el("path", { class: "glifo", d: GLIFOS[n.tipo] || GLIFOS.desconhecido, transform: n.tipo === "salto" ? "scale(.75)" : "" }, g);
        if (d && d.alertar && !d.este_pc) el("circle", { class: "vigiado", cx: r * 0.72, cy: -r * 0.72, r: 5 }, g);
        const a = el("text", { y: r + 16 }, g);
        a.textContent = t1.length > 26 ? `${t1.slice(0, 25)}…` : t1;
        const b = el("text", { y: r + 30, class: "ip" }, g);
        b.textContent = t2;
      });
      if (focado) {
        const g = [...gN.children].find((x) => x.dataset.id === focado);
        if (g) g.focus({ preventScroll: true });
      }
    }

    function aplicarVista() {
      const w = svg.clientWidth, h = svg.clientHeight;
      cena.setAttribute("transform", `translate(${(w / 2 + vista.x).toFixed(1)},${(h / 2 + vista.y).toFixed(1)}) scale(${vista.k.toFixed(4)})`);
    }

    function enquadrar(suave) {
      const ps = nos.map((n) => pos.get(n.id)).filter(Boolean);
      if (!ps.length || !svg.clientWidth) return;
      const x0 = Math.min(...ps.map((p) => p.x)) - 90, x1 = Math.max(...ps.map((p) => p.x)) + 90;
      const y0 = Math.min(...ps.map((p) => p.y)) - 40, y1 = Math.max(...ps.map((p) => p.y)) + 72;
      const k = Math.max(0.3, Math.min(1.3, svg.clientWidth / (x1 - x0), svg.clientHeight / (y1 - y0)));
      const alvo = { k, x: -((x0 + x1) / 2) * k, y: -((y0 + y1) / 2) * k };
      if (suave && !calmo()) {
        vista.k += (alvo.k - vista.k) * 0.18; vista.x += (alvo.x - vista.x) * 0.18; vista.y += (alvo.y - vista.y) * 0.18;
      } else vista = alvo;
      aplicarVista();
    }

    function laco() {
      if (!vivo) return;
      const animando = nos.some((n) => pulsando(pos.get(n.id)));
      if (alpha >= 0.005 || sujo || animando) {
        passo();
        desenhar();
        sujo = false;
        if (!mexeuNaVista && nos.length > 1 && (alpha >= 0.005 || !enquadrado)) {   // a câmera acompanha até o desenho assentar
          enquadrar(alpha >= 0.005);
          if (alpha < 0.005) enquadrado = true;
        }
      }
      requestAnimationFrame(laco);
    }

    // ----------------------------------------------------------- interação
    function noMundo(ev) {
      const r = svg.getBoundingClientRect();
      return { x: (ev.clientX - r.left - r.width / 2 - vista.x) / vista.k, y: (ev.clientY - r.top - r.height / 2 - vista.y) / vista.k };
    }
    function zoom(fator) {
      vista.k = Math.min(3, Math.max(0.3, vista.k * fator));
      vista.x *= fator; vista.y *= fator;
      mexeuNaVista = true;
      aplicarVista();
    }
    const toques = new Map();
    let arrasto = null, pinca = null;
    const distancia = () => { const [a, b] = [...toques.values()]; return Math.hypot(a.x - b.x, a.y - b.y) || 1; };

    svg.addEventListener("pointerdown", (ev) => {
      toques.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      if (toques.size === 2) { pinca = { dist: distancia(), k: vista.k }; arrasto = null; return; }
      const g = ev.target.closest(".no");
      arrasto = g ? { id: g.dataset.id, x0: ev.clientX, y0: ev.clientY, moveu: false }
        : { pan: true, x: ev.clientX - vista.x, y: ev.clientY - vista.y, x0: ev.clientX, y0: ev.clientY, moveu: false };
      svg.setPointerCapture(ev.pointerId);
      svg.classList.add("arrastando");
    });
    svg.addEventListener("pointermove", (ev) => {
      if (toques.has(ev.pointerId)) toques.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      if (pinca && toques.size === 2) {
        const novoK = Math.min(3, Math.max(0.3, pinca.k * (distancia() / pinca.dist)));
        zoom(novoK / vista.k);
        return;
      }
      if (!arrasto) return;
      if (Math.hypot(ev.clientX - arrasto.x0, ev.clientY - arrasto.y0) > 4) arrasto.moveu = true;
      if (!arrasto.moveu) return;
      mexeuNaVista = true;
      if (arrasto.pan) {
        vista.x = ev.clientX - arrasto.x; vista.y = ev.clientY - arrasto.y;
        aplicarVista();
        return;
      }
      const p = pos.get(arrasto.id), m = noMundo(ev);
      if (!p) return;
      p.x = m.x; p.y = m.y; p.fixo = true;
      alpha = Math.max(alpha, 0.3);
      sujo = true;
    });
    const soltar = (ev) => {
      toques.delete(ev.pointerId);
      if (toques.size < 2) pinca = null;
      if (arrasto && !arrasto.moveu && ev.type === "pointerup") selecionar(arrasto.pan ? null : arrasto.id, true);   // clique sem arrastar
      arrasto = null;
      svg.classList.remove("arrastando");
    };
    svg.addEventListener("pointerup", soltar);
    svg.addEventListener("pointercancel", soltar);
    svg.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      zoom(ev.deltaY < 0 ? 1.12 : 0.89);
    }, { passive: false });
    svg.addEventListener("keydown", (ev) => {
      const g = ev.target.closest && ev.target.closest(".no");
      if (g && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); selecionar(g.dataset.id, true); }
    });
    const observador = new ResizeObserver(() => { aplicarVista(); if (!mexeuNaVista) enquadrar(false); });
    observador.observe(svg);

    function selecionar(id, avisar) {
      selecionado = id;
      sujo = true;
      if (!avisar) return;
      const n = nos.find((x) => x.id === id);
      if (!n) { if (opcoes.aoSelecionar) opcoes.aoSelecionar(null); return; }
      if (n.d && opcoes.aoSelecionar) opcoes.aoSelecionar(n.d.id);
      else if (opcoes.aoSelecionarSalto) opcoes.aoSelecionarSalto(n);
    }

    aplicarVista();
    requestAnimationFrame(laco);
    return {
      atualizar: montar,
      selecionar: (id) => selecionar(id, false),
      filtrar(texto) { filtro = (texto || "").trim().toLowerCase(); sujo = true; },
      mostrarOffline(v) { mostrarOff = v; if (ultimoEstado) montar(ultimoEstado); },
      zoom,
      reorganizar() {
        pos.forEach((p, id) => { if (id !== centro) { p.fixo = false; p.x += (Math.random() - 0.5) * 40; p.y += (Math.random() - 0.5) * 40; } });
        alpha = 1; mexeuNaVista = false; enquadrado = false;
      },
      destruir() { vivo = false; observador.disconnect(); },
    };
  }

  HN.mapa = { criar, glifo, papelSalto, GLIFOS };
})(window.HN = window.HN || {});
