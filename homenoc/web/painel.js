/* HomeNOC: painel inicial. O "frontal" diz em uma frase se está tudo bem e
   mostra um LED por parte do sistema; abaixo vêm leituras, gráficos e eventos. */
"use strict";
(function (HN) {
  const { fmt, graficos } = HN;
  const { html, cru, pintar, glifo, situacao, roteadorDe, eixoMbps } = HN.ui;
  const PERIODOS = [[21600, "6 h", "6 horas"], [86400, "24 h", "24 horas"], [604800, "7 dias", "7 dias"]];
  const SEIS_HORAS = 21600;

  let raiz = null;
  let periodo = 86400;
  let internet = null, trafego = null, sparks = {};
  let cicloVisto, trafegoVisto, cargaEm = 0, cargaTrafegoEm = 0;

  const parte = (nome) => raiz && raiz.querySelector(`[data-parte="${nome}"]`);

  // ------------------------------------------------------------------ montagem
  function montar(el, estado) {
    raiz = el;
    internet = trafego = null;
    sparks = {};
    cicloVisto = trafegoVisto = undefined;
    periodo = Number(HN.ui.ler("painel.periodo", 86400)) || 86400;
    if (!PERIODOS.some((p) => p[0] === periodo)) periodo = 86400;
    pintar(el, html`
      <h1 class="sr">Painel</h1>
      <section class="frontal" aria-label="Situação da rede">
        <div class="veredito" data-parte="veredito" role="status"></div>
        <div class="portas" data-parte="portas"></div>
      </section>
      <section class="bloco" data-parte="primeiros" hidden></section>
      <section class="bloco placas" data-parte="placas" aria-label="Leituras de agora"></section>
      <div class="grade grade-3-2">
        <section class="bloco">
          <div class="bloco-cabeca"><h2>Internet</h2><span class="nota" data-parte="nota-internet"></span>
            <div class="acoes"><div class="segmentos" role="group" aria-label="Período do gráfico">${PERIODOS.map(([s, r]) => html`<button type="button" data-periodo="${s}" aria-pressed="${s === periodo}">${r}</button>`)}</div></div>
          </div>
          <div class="bloco-corpo" data-parte="grafico-internet"></div>
        </section>
        <section class="bloco">
          <div class="bloco-cabeca"><h2>Monitorados</h2><span class="nota">avisam quando caem</span><div class="acoes"><a class="botao pequeno" href="#aparelhos">Escolher</a></div></div>
          <ul class="lista" data-parte="monitorados"></ul>
        </section>
      </div>
      <div class="grade grade-3-2">
        <section class="bloco">
          <div class="bloco-cabeca"><h2>Tráfego da internet</h2><span class="nota">a casa toda, últimas 6 horas</span><div class="acoes"><a class="botao pequeno" href="#trafego">Detalhes</a></div></div>
          <div class="bloco-corpo" data-parte="grafico-trafego"></div>
        </section>
        <section class="bloco">
          <div class="bloco-cabeca"><h2>Últimos eventos</h2><div class="acoes"><a class="botao pequeno" href="#eventos">Ver todos</a></div></div>
          <ul class="eventos" data-parte="eventos"></ul>
        </section>
      </div>`, true);
    el.addEventListener("click", aoClicar);
    el.addEventListener("keydown", (ev) => {
      const linha = ev.target.closest(".monitorado[data-id]");
      if (linha && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); HN.gaveta.abrirDispositivo(linha.dataset.id); }
    });
    atualizar(estado);
  }

  function aoClicar(ev) {
    const alvo = ev.target.closest("[data-periodo], [data-ir], .monitorado[data-id], [data-alvo], [data-ocultar-passos]");
    if (!alvo) return;
    if (alvo.dataset.periodo) {
      periodo = Number(alvo.dataset.periodo);
      HN.ui.gravar("painel.periodo", periodo);
      raiz.querySelectorAll("[data-periodo]").forEach((b) => b.setAttribute("aria-pressed", String(b === alvo)));
      carregarInternet();
    } else if (alvo.dataset.ir) {
      const ir = alvo.dataset.ir;
      if (ir === "internet") HN.gaveta.abrirInternet();
      else if (ir === "roteador") HN.gaveta.abrirRoteador();
      else location.hash = ir;
    } else if (alvo.dataset.id) {
      HN.gaveta.abrirDispositivo(alvo.dataset.id);
    } else if (alvo.dataset.alvo) {
      abrirAlvo(alvo.dataset.alvo);
    } else if (alvo.dataset.ocultarPassos !== undefined) {
      HN.ui.gravar("primeiros.oculto", "1");
      parte("primeiros").hidden = true;
    }
  }

  function abrirAlvo(alvo) {
    if (alvo === "internet" || alvo.startsWith("wan:")) HN.gaveta.abrirInternet();
    else if (alvo.startsWith("dispositivo:")) {
      const id = alvo.slice("dispositivo:".length);
      if (HN.ui.dispositivo(id)) HN.gaveta.abrirDispositivo(id);
      else HN.ui.toast("Esse aparelho não está mais no inventário.");
    }
  }

  // ------------------------------------------------------------------ partes que mudam a cada leitura
  function pintarVeredito(estado) {
    const v = estado.veredito || { estado: "iniciando", titulo: "Verificando a rede", detalhe: "" };
    const el = parte("veredito");
    el.dataset.estado = v.estado;
    let quando = "";
    if (v.desde && v.estado !== "ok") {
      const t = estado.agora - v.desde;
      quando = t < 60 ? `Começou agora, às ${fmt.hora(v.desde)}.` : `Começou às ${fmt.hora(v.desde)}, há ${fmt.duracao(t)}.`;
    }
    else if (v.estado === "ok" && estado.internet && estado.internet.desde && estado.agora - estado.internet.desde > 3600) {
      quando = `Internet sem quedas há ${fmt.duracao(estado.agora - estado.internet.desde)}.`;
    }
    pintar(el, html`<span class="luz" aria-hidden="true"></span><h2>${v.titulo}</h2><p>${v.detalhe}</p>${quando ? html`<p class="desde">${quando}</p>` : ""}`);
  }

  const DESCRICAO = { ok: "funcionando", lento: "pede atenção", critico: "com problema", off: "inativo" };

  function pintarPortas(estado) {
    const i = estado.internet, lenta = (estado.monitor && estado.monitor.lenta_ms) || 150;
    const r = roteadorDe(estado), t = estado.trafego || {}, a = estado.alertas || {}, z = estado.zabbix || {};
    const canais = a.canais || [];
    const portas = [
      ["internet", "Internet", !i ? ["off", "testando"] : !i.online ? ["critico", "fora do ar"] : [i.ms > lenta ? "lento" : "ok", fmt.ms(i.ms)]],
      ["roteador", "Roteador", !r ? ["off", "procurando"] : r.online ? ["ok", fmt.ms(r.latencia)] : ["critico", "sem resposta"]],
      ["#trafego", "Tráfego", t.estado === "ativo" ? ["ok", t.agora ? fmt.bpsTexto(t.agora.rx_bps) : "medindo"]
        : t.estado === "indisponivel" ? ["off", "sem UPnP"] : t.estado === "desligado" ? ["off", "desligado"] : ["off", "procurando"]],
      ["#ajustes/alertas", "Alertas", !canais.length ? ["off", "desligados"] : a.fila ? ["lento", `${a.fila} na fila`]
        : a.ultimo_erro ? ["lento", "com falha"] : ["ok", canais.length === 1 ? canais[0] : `${canais.length} canais`]],
      ["#ajustes/zabbix", "Zabbix", !z.configurado ? ["off", "opcional"] : z.ok ? ["ok", `${z.hosts} hosts`]
        : z.ok === false ? ["lento", "sem conexão"] : ["off", "conectando"]],
    ];
    pintar(parte("portas"), portas.map(([ir, etiqueta, [st, leitura]]) => html`
      <button type="button" class="porta" data-estado="${st}" data-ir="${ir}" aria-label="${etiqueta}: ${DESCRICAO[st]}, ${leitura}">
        <span class="soquete" aria-hidden="true"><span class="led"></span></span>
        <span class="etiqueta">${etiqueta}</span><span class="leitura">${leitura}</span>
      </button>`));
  }

  function pintarPrimeiros(estado) {
    const el = parte("primeiros");
    const p = estado.primeiros_passos || {};
    const passos = [
      ["#aparelhos", "Varrer a rede", "Encontra os aparelhos e desenha o mapa.", p.varredura],
      ["#aparelhos", "Escolher o que monitorar", "Ligue o aviso nos aparelhos importantes.", p.monitorados > 1],
      ["#ajustes/alertas", "Receber alertas", "Telegram ou Discord, de graça.", p.alertas],
      ["#ajustes/celular", "Abrir no celular", "Pelo Wi-Fi de casa, com senha.", p.celular],
      ["#ajustes/zabbix", "Conectar o Zabbix", "Opcional, para quem já usa.", p.zabbix],
    ];
    const essenciais = passos.slice(0, 3).every((x) => x[3]);
    el.hidden = essenciais || HN.ui.ler("primeiros.oculto", "") === "1";
    if (el.hidden) return;
    const feitos = passos.filter((x) => x[3]).length;
    pintar(el, html`
      <div class="bloco-cabeca"><h2>Primeiros passos</h2><span class="nota">${feitos} de ${passos.length} feitos</span>
        <div class="acoes"><button type="button" class="botao pequeno" data-ocultar-passos>Ocultar</button></div></div>
      <ol class="primeiros">${passos.map(([href, titulo, texto, feito], i) => html`
        <li><a class="passo" href="${href}" data-feito="${Boolean(feito)}">
          <span class="marca-passo" aria-hidden="true">${feito ? "✓" : i + 1}</span>
          <b>${titulo}${feito ? html`<span class="sr"> (feito)</span>` : ""}</b><small>${texto}</small>
        </a></li>`)}</ol>`);
  }

  function pintarPlacas(estado) {
    const ds = estado.dispositivos || [];
    const online = ds.filter((d) => d.online).length;
    const v = estado.varredura || {}, i = estado.internet, t = estado.trafego || {};
    const ag = t.estado === "ativo" ? t.agora : null;
    const hoje = t.hoje || {};
    const dl = fmt.bps(ag ? ag.rx_bps : null);
    const medido = t.estado === "ativo" || hoje.rx_bytes || hoje.tx_bytes;
    const consumo = medido ? fmt.bytes((hoje.rx_bytes || 0) + (hoje.tx_bytes || 0)) : { n: "–", u: "" };
    const notaVarredura = v.ativa ? "Varrendo a rede agora…" : v.ultima ? `Última varredura ${fmt.ha(v.ultima, estado.agora)}` : "Primeira varredura em andamento";
    let internetValor = html`–`, internetNota = "Aguardando o primeiro teste";
    if (i && i.online) {
      const [n, u] = fmt.ms(i.ms).split(" ");
      internetValor = html`${n}<small>${u || ""}</small>`;
      internetNota = i.servidores.map((s) => `${s.nome} ${s.online ? fmt.ms(s.ms) : "sem resposta"}`).join(", ");
    } else if (i) {
      internetValor = html`Fora`;
      internetNota = "Nenhum servidor respondeu";
    }
    const semTrafego = { indisponivel: "Ative o UPnP no roteador para medir", desligado: "Medição desligada nos ajustes", procurando: "Procurando o roteador…" }[t.estado] || "Medindo…";
    pintar(parte("placas"), html`
      <a class="placa" href="#aparelhos">
        <span class="placa-rotulo">Aparelhos na rede</span>
        <span class="placa-valor end">${online}<small>de ${ds.length}</small></span>
        <span class="placa-nota">${notaVarredura}</span>
      </a>
      <button type="button" class="placa" data-ir="internet">
        <span class="placa-rotulo">Internet</span>
        <span class="placa-valor end">${internetValor}</span>
        <span class="placa-nota">${internetNota}</span>
      </button>
      <a class="placa" href="#trafego">
        <span class="placa-rotulo"><i style="background:var(--s1)"></i>Download agora</span>
        <span class="placa-valor end">${dl.n}<small>${dl.u}</small></span>
        <span class="placa-nota">${ag ? `Upload ${fmt.bpsTexto(ag.tx_bps)}` : semTrafego}</span>
      </a>
      <a class="placa" href="#trafego">
        <span class="placa-rotulo">Consumo hoje</span>
        <span class="placa-valor end">${consumo.n}<small>${consumo.u}</small></span>
        <span class="placa-nota">${hoje.rx_bytes || hoje.tx_bytes ? `${fmt.bytesTexto(hoje.rx_bytes)} baixados, ${fmt.bytesTexto(hoje.tx_bytes)} enviados` : "Desde a meia-noite"}</span>
      </a>`);
  }

  function pintarMonitorados(estado) {
    const lista = (estado.dispositivos || []).filter((d) => d.alertar && !d.este_pc);
    if (!lista.length) {
      pintar(parte("monitorados"), html`<li>${HN.ui.vazio("Nenhum aparelho monitorado", html`Abra um aparelho em <a href="#aparelhos">Aparelhos</a> e ligue “Avisar quando cair”.`)}</li>`);
      return;
    }
    HN.ui.preservarFoco(parte("monitorados"), () => pintar(parte("monitorados"), lista.map((d) => {
      const s = situacao(d);
      const detalhe = d.online ? (d.latencia != null ? fmt.ms(d.latencia) : "") : d.mudou_em ? fmt.ha(d.mudou_em, estado.agora) : "";
      const sp = sparks[d.id];
      return html`<li class="monitorado" data-id="${d.id}" tabindex="0" role="button" aria-label="${d.nome}: ${s.texto}${detalhe ? `, ${detalhe}` : ""}. Abrir detalhes">
        <span class="icone-tipo">${glifo(d.tipo)}</span>
        <div><div class="nome">${d.nome}</div><div class="sub"><span class="estado" data-estado="${s.estado}">${s.texto}${detalhe ? `, ${detalhe}` : ""}</span></div></div>
        ${sp ? cru(graficos.minigrafico(sp.serie, sp.desde, sp.ate, { lacuna: 1500 })) : cru('<svg class="spark" aria-hidden="true"></svg>')}
      </li>`;
    })));
  }

  function linhaEvento(e, agora) {
    const hoje = new Date(e.ts * 1000).toDateString() === new Date(agora * 1000).toDateString();
    const quando = hoje ? fmt.hora(e.ts) : new Date(e.ts * 1000).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
    const clicavel = e.alvo && (e.alvo === "internet" || e.alvo.startsWith("dispositivo:"));
    return html`<li class="evento" data-gravidade="${e.gravidade}">
      <time datetime="${new Date(e.ts * 1000).toISOString()}" title="${fmt.dataHora(e.ts)}">${quando}</time>
      <span class="marcador" aria-hidden="true"></span>
      <div>${clicavel ? html`<button type="button" class="link-evento" data-alvo="${e.alvo}">${e.titulo}</button>` : html`<b>${e.titulo}</b>`}${e.detalhe ? html`<small>${e.detalhe}</small>` : ""}</div>
    </li>`;
  }

  function pintarEventos(estado) {
    const eventos = (estado.eventos || []).slice(0, 7);
    pintar(parte("eventos"), eventos.length ? eventos.map((e) => linhaEvento(e, estado.agora))
      : html`<li>${HN.ui.vazio("Nada aconteceu ainda", "Quedas, retornos e aparelhos novos aparecem aqui.")}</li>`);
  }

  // ------------------------------------------------------------------ gráficos
  async function carregarInternet() {
    cargaEm = Date.now();
    const estado = HN.S.estado;
    const monitorados = ((estado && estado.dispositivos) || []).filter((d) => d.alertar && !d.este_pc);
    const pedidos = [HN.api("GET", `/api/historico?alvo=internet&periodo=${periodo}`)]
      .concat(monitorados.map((d) => HN.api("GET", `/api/historico?alvo=${encodeURIComponent(`dispositivo:${d.id}`)}&periodo=${SEIS_HORAS}`)));
    const respostas = await Promise.allSettled(pedidos);
    if (!raiz) return;
    if (respostas[0].status === "fulfilled") internet = respostas[0].value;
    monitorados.forEach((d, k) => { const r = respostas[k + 1]; if (r.status === "fulfilled") sparks[d.id] = r.value; });
    desenharInternet();
    if (HN.S.estado) pintarMonitorados(HN.S.estado);
  }

  function desenharInternet() {
    const caixa = parte("grafico-internet");
    if (!caixa || !internet) return;
    const passo = (internet.ate - internet.desde) / 240;
    const nome = (PERIODOS.find((p) => p[0] === periodo) || PERIODOS[1])[2];
    graficos.linhas(caixa, {
      series: [{ nome: "Tempo de resposta", cor: "var(--s1)", area: true, pontos: internet.serie.map((p) => [p[0], p[1]]) }],
      perdas: internet.serie.map((p) => [p[0], p[2]]),
      t0: internet.desde, t1: internet.ate, altura: 220, lacuna: passo * 4, unidade: "ms", dicaY: fmt.ms, padraoY: 50,
      rotulo: `Tempo de resposta da internet nas últimas ${nome}`,
      vazio: "O primeiro ponto aparece depois do primeiro teste, que roda a cada minuto.",
    });
    const e = internet.estatisticas || {};
    pintar(parte("nota-internet"), !e.amostras ? "" : e.media == null ? `nenhum dos ${e.amostras} testes respondeu`
      : `média de ${fmt.ms(e.media)}, respondeu em ${fmt.pct(e.disponibilidade)} dos testes`);
  }

  async function carregarTrafego() {
    cargaTrafegoEm = Date.now();
    try {
      trafego = await HN.api("GET", `/api/trafego?periodo=${SEIS_HORAS}`);
    } catch (e) { return; }
    if (raiz) desenharTrafego();
  }

  function desenharTrafego() {
    const caixa = parte("grafico-trafego");
    if (!caixa || !trafego) return;
    const st = trafego.status || {};
    if (!trafego.serie.length && st.estado !== "ativo") {
      const motivo = st.estado === "desligado" ? "A medição de tráfego está desligada nos ajustes."
        : st.estado === "indisponivel" ? "O roteador não respondeu ao UPnP, que é por onde o HomeNOC lê o tráfego." : "Procurando o roteador…";
      pintar(caixa, html`<div class="vazio"><b>Sem medição de tráfego</b>${motivo} <a href="#trafego">Como resolver</a></div>`, true);
      return;
    }
    const passo = (trafego.ate - trafego.desde) / 240;
    graficos.linhas(caixa, {
      series: [
        { nome: "Download", cor: "var(--s1)", area: true, pontos: trafego.serie.map((p) => [p[0], p[1] / 1e6]) },
        { nome: "Upload", cor: "var(--s2)", pontos: trafego.serie.map((p) => [p[0], p[2] / 1e6]) },
      ],
      t0: trafego.desde, t1: trafego.ate, altura: 200, lacuna: passo * 4, unidade: "Mbps", eixoY: eixoMbps,
      dicaY: (v) => fmt.bpsTexto(v * 1e6), textoSemValor: "sem medição", rotulo: "Download e upload da casa nas últimas 6 horas",
      vazio: "Os primeiros pontos aparecem em cerca de um minuto.",
    });
  }

  // ------------------------------------------------------------------ ciclo de vida
  function atualizar(estado) {
    if (!raiz || !estado) return;
    pintarVeredito(estado);
    pintarPortas(estado);
    pintarPrimeiros(estado);
    pintarPlacas(estado);
    pintarMonitorados(estado);
    pintarEventos(estado);
    const ciclo = estado.monitor && estado.monitor.ultimo_ciclo;
    const monitorados = (estado.dispositivos || []).filter((d) => d.alertar && !d.este_pc).map((d) => d.id).join();
    if (cicloVisto === undefined || ((ciclo !== cicloVisto || monitorados !== raiz.dataset.monitorados) && Date.now() - cargaEm > 20000)) {
      cicloVisto = ciclo;
      raiz.dataset.monitorados = monitorados;
      carregarInternet();
    }
    const t = estado.trafego && estado.trafego.agora ? estado.trafego.agora.ts : null;
    if (trafegoVisto === undefined || (t !== trafegoVisto && Date.now() - cargaTrafegoEm > 25000)) {
      trafegoVisto = t;
      carregarTrafego();
    }
  }

  HN.visoes.painel = {
    titulo: "Painel",
    montar, atualizar,
    redesenhar() { desenharInternet(); desenharTrafego(); },
    desmontar() { raiz = null; },
  };
})(window.HN = window.HN || {});
