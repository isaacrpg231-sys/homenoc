/* HomeNOC: formatação em pt-BR e gráficos em SVG feitos à mão (sem bibliotecas).
   Regras: linhas de 2px, área a 10%, grade em linha fina, legenda para 2+ séries,
   dica que acompanha o ponteiro (e as setas do teclado) e uma visão em tabela. */
"use strict";
(function (HN) {
  const NS = "http://www.w3.org/2000/svg";
  const nf = (min, max) => new Intl.NumberFormat("pt-BR", { minimumFractionDigits: min, maximumFractionDigits: max });
  const NF0 = nf(0, 0), NF1 = nf(1, 1), NF2 = nf(0, 2);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const fmt = {
    esc,
    ms(v) {
      if (v == null || Number.isNaN(v)) return "–";
      return (v < 10 ? NF1.format(v) : NF0.format(v)) + " ms";
    },
    bps(v) {
      if (v == null || Number.isNaN(v)) return { n: "–", u: "" };
      if (v >= 1e9) return { n: NF1.format(v / 1e9), u: "Gbps" };
      if (v >= 1e6) return { n: (v >= 1e8 ? NF0 : NF1).format(v / 1e6), u: "Mbps" };
      if (v >= 1e3) return { n: NF0.format(v / 1e3), u: "kbps" };
      return { n: NF0.format(v), u: "bps" };
    },
    bpsTexto(v) { const f = fmt.bps(v); return f.u ? `${f.n} ${f.u}` : f.n; },
    bytes(v) {
      if (v == null) return { n: "–", u: "" };
      if (v >= 1e12) return { n: NF2.format(v / 1e12), u: "TB" };
      if (v >= 1e9) return { n: (v >= 1e11 ? NF0 : NF1).format(v / 1e9), u: "GB" };
      if (v >= 1e6) return { n: NF0.format(v / 1e6), u: "MB" };
      return { n: NF0.format(v / 1e3), u: "kB" };
    },
    bytesTexto(v) { const f = fmt.bytes(v); return `${f.n} ${f.u}`; },
    hora(t) { return new Date(t * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }); },
    diaCurto(t) { return new Date(t * 1000).toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit" }).replace(".", ""); },
    dataHora(t) {
      return new Date(t * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    },
    diaLongo(t) {
      const d = new Date(t * 1000), hoje = new Date(), ontem = new Date(Date.now() - 86400000);
      if (d.toDateString() === hoje.toDateString()) return "Hoje";
      if (d.toDateString() === ontem.toDateString()) return "Ontem";
      const s = d.toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
      return s.charAt(0).toUpperCase() + s.slice(1);
    },
    duracao(s) {
      if (s == null) return "–";
      s = Math.max(0, s);
      if (s < 60) return "menos de 1 min";
      const m = Math.floor(s / 60);
      if (m < 60) return `${m} min`;
      const h = Math.floor(m / 60);
      if (h < 24) return `${h} h ${String(m % 60).padStart(2, "0")} min`;
      return `${Math.floor(h / 24)} d ${h % 24} h`;
    },
    ha(t, agora) { return t ? (agora - t < 60 ? "há menos de 1 min" : `há ${fmt.duracao(agora - t)}`) : "–"; },
    pct(v) {
      if (v == null) return "–";
      if (v >= 100) return "100%";
      return `${(v >= 99.9 ? NF2 : NF1).format(v)}%`;    // 99,95% não vira "100,0%"
    },
  };

  // ------------------------------------------------------------------ escalas
  function topoBonito(v) {
    if (!(v > 0)) return 1;
    const exp = Math.pow(10, Math.floor(Math.log10(v)));
    const f = v / exp;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * exp;
  }

  /* Topo e passo do eixo Y: de 3 a 6 divisões de 1, 2, 2,5 ou 5 × 10^n, com o menor topo possível. */
  function escala(maximo) {
    if (!(maximo > 0)) return { topo: 1, passo: 0.25, n: 4 };
    const exp = Math.floor(Math.log10(maximo));
    let melhor = null;
    for (let e = exp - 2; e <= exp + 1; e++) {
      for (const f of [1, 2, 2.5, 5]) {
        const passo = f * Math.pow(10, e);
        const n = Math.ceil(maximo / passo - 1e-9);
        if (n < 3 || n > 6) continue;
        const topo = n * passo;
        if (!melhor || topo < melhor.topo - 1e-9 || (Math.abs(topo - melhor.topo) < 1e-9 && n < melhor.n)) melhor = { topo, passo, n };
      }
    }
    return melhor || { topo: topoBonito(maximo), passo: topoBonito(maximo) / 4, n: 4 };
  }
  const casasDoPasso = (passo) => (passo >= 1 && Number.isInteger(passo) ? 0 : passo >= 0.1 ? 1 : 2);

  function marcasTempo(t0, t1) {
    const faixa = t1 - t0;
    const passo = faixa <= 3700 ? 900 : faixa <= 6 * 3600 + 100 ? 3600 : faixa <= 26 * 3600 ? 4 * 3600 : 86400;
    const fuso = new Date().getTimezoneOffset() * 60;
    const lista = [];
    for (let t = Math.ceil((t0 - fuso) / passo) * passo + fuso; t <= t1; t += passo) lista.push(t);
    return { lista, passo };
  }

  function rotuloTempo(t, passo) {
    if (passo >= 86400) return fmt.diaCurto(t);
    return fmt.hora(t);
  }

  function el(tag, attrs, pai, texto) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    if (texto != null) e.textContent = texto;
    if (pai) pai.appendChild(e);
    return e;
  }

  function legenda(series, caixa) {
    const ul = document.createElement("ul");
    ul.className = "legenda";
    series.forEach((s) => {
      const li = document.createElement("li");
      const i = document.createElement("i");
      if (caixa) i.className = "caixa";
      i.style.background = s.cor;
      li.append(i, document.createTextNode(s.nome));
      ul.appendChild(li);
    });
    return ul;
  }

  function botaoTabela(envoltorio, desenharTabela) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "botao pequeno";
    b.textContent = "Ver tabela";
    b.setAttribute("aria-pressed", "false");
    b.addEventListener("click", () => {
      const tabela = envoltorio.querySelector(".grafico-tabela");
      const grafico = envoltorio.querySelector(".grafico");
      const abrir = tabela.hidden;
      if (abrir && !tabela.firstChild) desenharTabela(tabela);
      tabela.hidden = !abrir;
      grafico.hidden = abrir;
      b.textContent = abrir ? "Ver gráfico" : "Ver tabela";
      b.setAttribute("aria-pressed", String(abrir));
    });
    return b;
  }

  // ------------------------------------------------------------------ gráfico de linhas
  /* opts: series [{nome, cor, pontos: [[t, v|null], ...], area}], t0, t1, altura,
     eixoY(v) -> texto, unidade (texto no topo do eixo), dicaY(v) -> texto, perdas [[t, %], ...],
     lacuna (s): pontos mais distantes que isso não são ligados, rotulo (para leitores de tela) */
  function linhas(container, opts) {
    container.innerHTML = "";
    const series = opts.series.filter((s) => s.pontos);
    const cabeca = document.createElement("div");
    cabeca.style.cssText = "display:flex;align-items:center;gap:8px;justify-content:space-between;flex-wrap:wrap";
    cabeca.appendChild(series.length > 1 || opts.perdas ? legenda([...series, ...(opts.perdas ? [{ nome: "Sem resposta", cor: "var(--critical)" }] : [])]) : document.createElement("span"));
    const grafico = document.createElement("div");
    grafico.className = "grafico";
    const tabela = document.createElement("div");
    tabela.className = "grafico-tabela";
    tabela.hidden = true;
    if (opts.tabela !== false) cabeca.appendChild(botaoTabela(container, (alvo) => desenharTabelaLinhas(alvo, series, opts)));
    container.append(cabeca, grafico, tabela);

    const todos = series.flatMap((s) => s.pontos.map((p) => p[1])).filter((v) => v != null);
    const soPerdas = !todos.length && opts.perdas && opts.perdas.some((p) => p[1] > 0);   // tudo falhou: mostra as marcas vermelhas
    if (!todos.length && !soPerdas) {
      grafico.innerHTML = `<div class="vazio"><b>Ainda sem dados neste período</b>${esc(opts.vazio || "O gráfico aparece depois das primeiras medições.")}</div>`;
      const b = cabeca.querySelector("button");
      if (b) b.remove();
      return;
    }
    const W = Math.max(280, grafico.clientWidth || container.clientWidth || 600);
    const H = opts.altura || 210;
    const L = 46, R = 14, T = 16, B = 24 + (opts.perdas ? 8 : 0);
    const t0 = opts.t0, t1 = opts.t1;
    const { topo: maximo, passo: passoY, n: divisoes } = escala(todos.length ? Math.max(...todos) * 1.08 : (opts.padraoY || 1));
    const formatoY = nf(0, casasDoPasso(passoY));
    const x = (t) => L + ((t - t0) / (t1 - t0)) * (W - L - R);
    const y = (v) => T + (1 - v / maximo) * (H - T - B);
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", tabindex: 0, "aria-label": opts.rotulo || "Gráfico" });
    grafico.appendChild(svg);

    // grade e eixo Y
    for (let i = 0; i <= divisoes; i++) {
      const v = i * passoY;
      el("line", { class: i === 0 ? "base" : "grade-linha", x1: L, x2: W - R, y1: y(v), y2: y(v) }, svg);
      el("text", { x: L - 8, y: y(v) + 4, "text-anchor": "end" }, svg, opts.eixoY ? opts.eixoY(v, maximo) : formatoY.format(v));
    }
    if (opts.unidade) el("text", { x: L - 8, y: 6, "text-anchor": "end", class: "forte" }, svg, opts.unidade);
    // eixo X
    const { lista, passo } = marcasTempo(t0, t1);
    lista.forEach((t) => {
      const px = x(t);
      if (px < L + 16 || px > W - R - 16) return;
      el("text", { x: px, y: H - 6, "text-anchor": "middle" }, svg, rotuloTempo(t, passo));
    });
    // perdas de pacote: marcas vermelhas sob o eixo
    if (opts.perdas) {
      const largura = Math.max(2, (W - L - R) / 240);
      opts.perdas.filter((p) => p[1] > 0).forEach(([t, pct]) => {
        el("rect", { class: "perda", x: x(t) - largura / 2, y: H - B + 4, width: largura, height: 6, opacity: 0.35 + 0.65 * Math.min(1, pct / 100) }, svg);
      });
    }
    // séries
    const lacuna = opts.lacuna || Infinity;
    series.forEach((s) => {
      const segmentos = [];
      let atual = [];
      s.pontos.forEach((p) => {
        if (p[1] == null || (atual.length && p[0] - atual[atual.length - 1][0] > lacuna)) {
          if (atual.length) segmentos.push(atual);
          atual = p[1] == null ? [] : [p];
        } else atual.push(p);
      });
      if (atual.length) segmentos.push(atual);
      segmentos.forEach((seg) => {
        const d = seg.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
        if (s.area && seg.length > 1) {
          el("path", { class: "area", d: `${d}L${x(seg[seg.length - 1][0]).toFixed(1)},${y(0)}L${x(seg[0][0]).toFixed(1)},${y(0)}Z`, style: `fill:${s.cor}` }, svg);
        }
        if (seg.length > 1) el("path", { class: "linha", d, style: `stroke:${s.cor}` }, svg);
        else el("circle", { cx: x(seg[0][0]), cy: y(seg[0][1]), r: 2, style: `fill:${s.cor}` }, svg);
      });
      const ultimo = [...s.pontos].reverse().find((p) => p[1] != null);
      if (ultimo) el("circle", { class: "ponto-final", cx: x(ultimo[0]), cy: y(ultimo[1]), r: 4, style: `fill:${s.cor}` }, svg);
    });

    // mira + dica (ponteiro e teclado)
    const mira = el("line", { class: "mira", y1: T, y2: H - B, visibility: "hidden" }, svg);
    const marcadores = series.map((s) => el("circle", { r: 4, class: "ponto-final", style: `fill:${s.cor}`, visibility: "hidden" }, svg));
    const dica = document.createElement("div");
    dica.className = "dica-grafico";
    dica.hidden = true;
    grafico.appendChild(dica);
    const base = series[0].pontos;
    let indice = -1;
    function mostrar(i) {
      if (i < 0 || i >= base.length) return esconder();
      indice = i;
      const t = base[i][0], px = x(t);
      mira.setAttribute("x1", px); mira.setAttribute("x2", px); mira.setAttribute("visibility", "visible");
      dica.innerHTML = `<time>${esc(fmt.dataHora(t))}</time>`;
      series.forEach((s, k) => {
        const v = s.pontos[i] ? s.pontos[i][1] : null;
        const linha = document.createElement("div");
        const chave = document.createElement("i");
        chave.style.background = s.cor;
        const valor = document.createElement("b");
        valor.textContent = v == null ? (opts.textoSemValor || "sem resposta") : (opts.dicaY ? opts.dicaY(v) : NF1.format(v));
        const nome = document.createElement("span");
        nome.textContent = s.nome;
        linha.append(chave, valor, nome);
        dica.appendChild(linha);
        if (v != null) {
          marcadores[k].setAttribute("cx", px); marcadores[k].setAttribute("cy", y(v)); marcadores[k].setAttribute("visibility", "visible");
        } else marcadores[k].setAttribute("visibility", "hidden");
      });
      const perda = opts.perdas && opts.perdas[i] ? opts.perdas[i][1] : 0;
      if (perda > 0 && perda < 100) {
        const extra = document.createElement("div");
        extra.innerHTML = `<i style="background:var(--critical)"></i><b>${NF0.format(perda)}%</b><span>das medições sem resposta</span>`;
        dica.appendChild(extra);
      }
      dica.hidden = false;
      const largura = svg.getBoundingClientRect().width || W;
      const escala = largura / W;
      const esquerda = Math.min(Math.max(px * escala - dica.offsetWidth / 2, 0), largura - dica.offsetWidth);
      dica.style.left = `${esquerda}px`;
      dica.style.top = `${Math.max(0, T * escala - 6)}px`;
    }
    function esconder() {
      indice = -1;
      dica.hidden = true;
      mira.setAttribute("visibility", "hidden");
      marcadores.forEach((m) => m.setAttribute("visibility", "hidden"));
    }
    function maisProximo(t) {
      let lo = 0, hi = base.length - 1;
      while (hi - lo > 1) { const m = (lo + hi) >> 1; if (base[m][0] < t) lo = m; else hi = m; }
      return Math.abs(base[lo][0] - t) <= Math.abs(base[hi][0] - t) ? lo : hi;
    }
    svg.addEventListener("pointermove", (e) => {
      const r = svg.getBoundingClientRect();
      const px = ((e.clientX - r.left) / r.width) * W;
      if (px < L || px > W - R) return esconder();
      mostrar(maisProximo(t0 + ((px - L) / (W - L - R)) * (t1 - t0)));
    });
    svg.addEventListener("pointerleave", esconder);
    svg.addEventListener("blur", esconder);
    svg.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        const passoTecla = e.shiftKey ? 10 : 1;
        mostrar(indice < 0 ? base.length - 1 : Math.max(0, Math.min(base.length - 1, indice + (e.key === "ArrowLeft" ? -passoTecla : passoTecla))));
      } else if (e.key === "Escape") esconder();
    });
  }

  function desenharTabelaLinhas(alvo, series, opts) {
    const linhasTabela = series[0].pontos.map((p, i) => {
      const celulas = series.map((s) => {
        const v = s.pontos[i] ? s.pontos[i][1] : null;
        return `<td>${v == null ? "–" : esc(opts.dicaY ? opts.dicaY(v) : NF1.format(v))}</td>`;
      }).join("");
      return `<tr><td>${esc(fmt.dataHora(p[0]))}</td>${celulas}</tr>`;
    }).reverse().join("");
    alvo.innerHTML = `<table><thead><tr><th>Horário</th>${series.map((s) => `<th>${esc(s.nome)}</th>`).join("")}</tr></thead><tbody>${linhasTabela}</tbody></table>`;
  }

  // ------------------------------------------------------------------ colunas agrupadas
  /* opts: categorias [{rotulo, valores: [v1, v2], dica}], series [{nome, cor}], formatar(v), altura */
  function colunas(container, opts) {
    container.innerHTML = "";
    const cabeca = document.createElement("div");
    cabeca.style.cssText = "display:flex;align-items:center;gap:8px;justify-content:space-between;flex-wrap:wrap";
    cabeca.appendChild(legenda(opts.series, true));
    const grafico = document.createElement("div");
    grafico.className = "grafico";
    const tabela = document.createElement("div");
    tabela.className = "grafico-tabela";
    tabela.hidden = true;
    cabeca.appendChild(botaoTabela(container, (alvo) => {
      const corpo = opts.categorias.map((c) => `<tr><td>${esc(c.rotulo)}</td>${c.valores.map((v) => `<td>${esc(opts.formatar(v))}</td>`).join("")}</tr>`).join("");
      alvo.innerHTML = `<table><thead><tr><th>Dia</th>${opts.series.map((s) => `<th>${esc(s.nome)}</th>`).join("")}</tr></thead><tbody>${corpo}</tbody></table>`;
    }));
    container.append(cabeca, grafico, tabela);
    if (!opts.categorias.length) {
      grafico.innerHTML = `<div class="vazio"><b>Ainda sem consumo registrado</b>Os dias aparecem conforme o tráfego é medido.</div>`;
      const b = cabeca.querySelector("button");
      if (b) b.remove();
      return;
    }
    const W = Math.max(280, grafico.clientWidth || 600), H = opts.altura || 200;
    const L = 8, R = 8, T = 22, B = 26;
    const maximo = escala(Math.max(1, ...opts.categorias.flatMap((c) => c.valores)) * 1.1).topo;
    const faixa = (W - L - R) / opts.categorias.length;
    const n = opts.series.length;
    const largura = Math.min(24, (faixa * 0.7 - (n - 1) * 2) / n);
    const y = (v) => T + (1 - v / maximo) * (H - T - B);
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": opts.rotulo || "Gráfico de colunas" });
    grafico.appendChild(svg);
    el("line", { class: "base", x1: L, x2: W - R, y1: y(0), y2: y(0) }, svg);
    const dica = document.createElement("div");
    dica.className = "dica-grafico";
    dica.hidden = true;
    grafico.appendChild(dica);
    opts.categorias.forEach((c, i) => {
      const centro = L + faixa * (i + 0.5);
      const inicio = centro - (n * largura + (n - 1) * 2) / 2;
      const grupo = el("g", { tabindex: 0, role: "img", "aria-label": `${c.rotulo}: ${c.valores.map((v, k) => `${opts.series[k].nome} ${opts.formatar(v)}`).join(", ")}` }, svg);
      c.valores.forEach((v, k) => {
        const x0 = inicio + k * (largura + 2), topo = y(v), base = y(0), r = Math.min(4, (base - topo) / 2, largura / 2);
        const d = v > 0
          ? `M${x0},${base}V${topo + r}Q${x0},${topo} ${x0 + r},${topo}H${x0 + largura - r}Q${x0 + largura},${topo} ${x0 + largura},${topo + r}V${base}Z`
          : `M${x0},${base}h${largura}`;
        el("path", { d, class: "barra-dado", style: `fill:${opts.series[k].cor}` }, grupo);
      });
      if (c.valores[0] > 0) {
        el("text", { x: inicio + largura / 2, y: y(c.valores[0]) - 6, "text-anchor": "middle", class: "forte" }, grupo, opts.formatarCurto ? opts.formatarCurto(c.valores[0]) : opts.formatar(c.valores[0]));
      }
      el("text", { x: centro, y: H - 7, "text-anchor": "middle" }, grupo, c.rotulo);
      el("rect", { x: centro - faixa / 2, y: T - 18, width: faixa, height: H - T - B + 18, fill: "transparent" }, grupo);
      const mostrar = () => {
        dica.innerHTML = `<time>${esc(c.dica || c.rotulo)}</time>` + c.valores.map((v, k) => `<div><i style="background:${opts.series[k].cor}"></i><b>${esc(opts.formatar(v))}</b><span>${esc(opts.series[k].nome)}</span></div>`).join("");
        dica.hidden = false;
        const r = svg.getBoundingClientRect(), escala = (r.width || W) / W;
        dica.style.left = `${Math.min(Math.max(centro * escala - dica.offsetWidth / 2, 0), (r.width || W) - dica.offsetWidth)}px`;
        dica.style.top = "0px";
        svg.querySelectorAll(".barra-dado").forEach((b) => b.classList.toggle("apagada", !grupo.contains(b)));
      };
      const esconder = () => { dica.hidden = true; svg.querySelectorAll(".barra-dado").forEach((b) => b.classList.remove("apagada")); };
      grupo.addEventListener("pointerenter", mostrar);
      grupo.addEventListener("pointerleave", esconder);
      grupo.addEventListener("focus", mostrar);
      grupo.addEventListener("blur", esconder);
    });
  }

  // ------------------------------------------------------------------ minigráfico
  function minigrafico(pontos, t0, t1, opcoes = {}) {
    const W = opcoes.largura || 112, H = opcoes.altura || 32, P = 4;
    const validos = pontos.filter((p) => p[1] != null);
    const perdas = pontos.filter((p) => p[1] == null || (p[2] && p[2] > 0));
    if (validos.length < 2) return `<svg class="spark" viewBox="0 0 ${W} ${H}" aria-hidden="true"></svg>`;
    const max = Math.max(...validos.map((p) => p[1])) * 1.15 || 1;
    const x = (t) => P + ((t - t0) / (t1 - t0)) * (W - 2 * P);
    const y = (v) => H - P - (v / max) * (H - 2 * P);
    let d = "", aberto = false, anterior = null;
    pontos.forEach((p) => {
      if (p[1] == null || (anterior && p[0] - anterior > (opcoes.lacuna || 600))) aberto = false;
      if (p[1] != null) { d += `${aberto ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`; aberto = true; anterior = p[0]; }
    });
    const ultimo = validos[validos.length - 1];
    const marcas = perdas.map((p) => `<rect x="${(x(p[0]) - 1).toFixed(1)}" y="${H - 3}" width="2" height="3" fill="var(--critical)"/>`).join("");
    return `<svg class="spark" viewBox="0 0 ${W} ${H}" aria-hidden="true">${marcas}<path d="${d}" fill="none" stroke="var(--s1)" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/><circle cx="${x(ultimo[0]).toFixed(1)}" cy="${y(ultimo[1]).toFixed(1)}" r="2.6" fill="var(--s1)"/></svg>`;
  }

  HN.fmt = fmt;
  HN.graficos = { linhas, colunas, minigrafico, topoBonito, escala };
})(window.HN = window.HN || {});
