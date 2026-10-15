/* HomeNOC: tráfego da internet (contadores do roteador via UPnP) e o histórico
   de eventos (quedas, retornos, aparelhos novos e alertas enviados). */
"use strict";
(function (HN) {
  const { fmt, graficos } = HN;
  const { html, cru, pintar, icone, toast, ocupado, eixoMbps } = HN.ui;

  // =================================================================== tráfego
  const PERIODOS = [[3600, "1 hora", "na última hora"], [21600, "6 horas", "nas últimas 6 horas"], [86400, "24 horas", "nas últimas 24 horas"], [604800, "7 dias", "nos últimos 7 dias"]];
  let raizT = null, periodo = 21600, dados = null, cargaEm = 0, amostraVista;

  const parteT = (nome) => raizT && raizT.querySelector(`[data-parte="${nome}"]`);

  function montarTrafego(el, estado) {
    raizT = el;
    dados = null;
    amostraVista = undefined;
    periodo = Number(HN.ui.ler("trafego.periodo", 21600)) || 21600;
    if (!PERIODOS.some((p) => p[0] === periodo)) periodo = 21600;
    pintar(el, html`
      <div class="visao-cabeca">
        <div><h1>Tráfego da internet</h1><p>Tudo o que a casa baixa e envia, lido do roteador por UPnP. Mostra o total da casa, não o que cada aparelho acessa.</p></div>
        <div class="acoes"><div class="segmentos" role="group" aria-label="Período">${PERIODOS.map(([s, r]) => html`<button type="button" data-periodo="${s}" aria-pressed="${s === periodo}">${r}</button>`)}</div></div>
      </div>
      <div data-parte="aviso"></div>
      <section class="bloco placas" data-parte="placas" aria-label="Resumo do tráfego"></section>
      <section class="bloco">
        <div class="bloco-cabeca"><h2>Velocidade</h2><span class="nota" data-parte="nota-grafico"></span></div>
        <div class="bloco-corpo" data-parte="grafico"></div>
      </section>
      <div class="grade grade-3-2">
        <section class="bloco">
          <div class="bloco-cabeca"><h2>Consumo por dia</h2><span class="nota">últimos 7 dias</span></div>
          <div class="bloco-corpo" data-parte="dias"></div>
        </section>
        <section class="bloco">
          <div class="bloco-cabeca"><h2>Sua conexão</h2><span class="nota">segundo o roteador</span></div>
          <div class="bloco-corpo" data-parte="conexao"></div>
        </section>
      </div>`, true);
    el.addEventListener("click", async (ev) => {
      const b = ev.target.closest("[data-periodo], [data-acao=ligar-trafego]");
      if (!b) return;
      if (b.dataset.periodo) {
        periodo = Number(b.dataset.periodo);
        HN.ui.gravar("trafego.periodo", periodo);
        el.querySelectorAll("[data-periodo]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        carregarTrafego();
      } else {
        try {
          await ocupado(b, "Ligando…", () => HN.api("POST", "/api/config", { trafego: { ativo: true } }));
          toast("Medição de tráfego ligada.");
          HN.app.atualizarJa();
        } catch (e) { toast(e.message, 5000); }
      }
    });
    atualizarTrafego(estado);
  }

  async function carregarTrafego() {
    cargaEm = Date.now();
    try {
      dados = await HN.api("GET", `/api/trafego?periodo=${periodo}`);
    } catch (e) {
      if (raizT) pintar(parteT("grafico"), HN.ui.vazio("Não consegui carregar o tráfego", e.message), true);
      return;
    }
    if (raizT) desenharTrafego();
  }

  function pintarAviso(estado) {
    const t = estado.trafego || {};
    const gw = estado.rede && estado.rede.gateway;
    let aviso = "";
    if (t.estado === "indisponivel") {
      const tecnico = t.motivo && !/^nenhum roteador respondeu/i.test(t.motivo) ? t.motivo : "";
      aviso = html`<div class="faixa"><span><b>O roteador não respondeu ao UPnP</b>, que é por onde o HomeNOC lê o tráfego.
        Entre na página do roteador, procure por <b>UPnP</b> (costuma ficar em Avançado, NAT ou Rede) e ative. O HomeNOC tenta de novo a cada 5 minutos.
        ${tecnico ? html`<br><small class="discreto">Detalhe: ${tecnico}</small>` : ""}</span>
        ${gw ? html`<a class="botao pequeno" href="http://${gw}" target="_blank" rel="noopener noreferrer">${icone("abrir")}Abrir a página do roteador</a>` : ""}</div>`;
    } else if (t.estado === "desligado") {
      aviso = html`<div class="faixa"><span>A medição do tráfego está desligada.</span><button type="button" class="botao pequeno primario" data-acao="ligar-trafego">Ligar a medição</button></div>`;
    } else if (t.estado === "procurando") {
      aviso = html`<div class="faixa"><span>Procurando o roteador na rede…</span></div>`;
    }
    pintar(parteT("aviso"), aviso);
  }

  function pintarPlacas(estado) {
    const t = estado.trafego || {};
    const ag = t.estado === "ativo" ? t.agora : null;
    const r = (dados && dados.resumo) || {};
    const dl = fmt.bps(ag ? ag.rx_bps : null), ul = fmt.bps(ag ? ag.tx_bps : null);
    const pico = fmt.bps(r.pico_rx_bps);
    const total = r.amostras ? fmt.bytes((r.rx_bytes || 0) + (r.tx_bytes || 0)) : { n: "–", u: "" };
    const noPeriodo = (PERIODOS.find((p) => p[0] === periodo) || PERIODOS[1])[2];
    pintar(parteT("placas"), html`
      <div class="placa"><span class="placa-rotulo"><i style="background:var(--s1)"></i>Download agora</span>
        <span class="placa-valor end">${dl.n}<small>${dl.u}</small></span><span class="placa-nota">${ag ? `medido ${fmt.ha(ag.ts, estado.agora)}` : "sem medição agora"}</span></div>
      <div class="placa"><span class="placa-rotulo"><i style="background:var(--s2)"></i>Upload agora</span>
        <span class="placa-valor end">${ul.n}<small>${ul.u}</small></span><span class="placa-nota">média dos últimos 30 segundos</span></div>
      <div class="placa"><span class="placa-rotulo">Maior download</span>
        <span class="placa-valor end">${pico.n}<small>${pico.u}</small></span><span class="placa-nota">${r.pico_em ? `em ${fmt.dataHora(r.pico_em)}` : noPeriodo}</span></div>
      <div class="placa"><span class="placa-rotulo">Total no período</span>
        <span class="placa-valor end">${total.n}<small>${total.u}</small></span><span class="placa-nota">${r.amostras ? `${fmt.bytesTexto(r.rx_bytes)} baixados, ${fmt.bytesTexto(r.tx_bytes)} enviados` : "sem medições no período"}</span></div>`);
  }

  function desenharTrafego() {
    if (!raizT || !dados) return;
    const passo = (dados.ate - dados.desde) / 240;
    graficos.linhas(parteT("grafico"), {
      series: [
        { nome: "Download", cor: "var(--s1)", area: true, pontos: dados.serie.map((p) => [p[0], p[1] / 1e6]) },
        { nome: "Upload", cor: "var(--s2)", pontos: dados.serie.map((p) => [p[0], p[2] / 1e6]) },
      ],
      t0: dados.desde, t1: dados.ate, altura: 260, lacuna: passo * 4, unidade: "Mbps", eixoY: eixoMbps,
      dicaY: (v) => fmt.bpsTexto(v * 1e6), textoSemValor: "sem medição", rotulo: "Velocidade de download e upload da casa",
      vazio: "Os primeiros pontos aparecem em cerca de um minuto depois que o roteador responde.",
    });
    const s = Math.max(passo, 30);
    pintar(parteT("nota-grafico"), !dados.serie.length ? "" : s < 60 ? `um ponto a cada ${Math.round(s)} segundos` : `cada ponto é a média de ${fmt.duracao(s)}`);
    const dias = (dados.dias || []).slice(-7).map((d) => {
      const ts = new Date(`${d.dia}T12:00:00`).getTime() / 1000;
      return { rotulo: fmt.diaCurto(ts), dica: fmt.diaLongo(ts), valores: [d.rx_bytes, d.tx_bytes] };
    });
    graficos.colunas(parteT("dias"), {
      categorias: dias, altura: 210, rotulo: "Consumo de internet por dia, download e upload",
      series: [{ nome: "Download", cor: "var(--s1)" }, { nome: "Upload", cor: "var(--s2)" }],
      formatar: fmt.bytesTexto, formatarCurto: (v) => { const b = fmt.bytes(v); return `${b.n} ${b.u}`; },
    });
    if (HN.S.estado) pintarPlacas(HN.S.estado);
  }

  function pintarConexao(estado) {
    const r = estado.trafego && estado.trafego.roteador;
    if (!r) {
      pintar(parteT("conexao"), html`<p class="dica">${estado.trafego && estado.trafego.estado === "ativo" ? "Lendo as informações da conexão…" : "Aparece quando o roteador responde ao UPnP."}</p>`);
      return;
    }
    const tipo = r.cgnat ? ["CGNAT", "A operadora divide este IP com outros clientes. Por isso não dá para abrir portas e acessar a casa de fora sem um serviço como VPN."]
      : r.nat_duplo ? ["NAT duplo", "Há outro roteador ou modem antes deste. Pode atrapalhar jogos online e o acesso remoto; dá para resolver colocando o modem em modo bridge."]
        : r.ip_publico ? ["IP público próprio", "O roteador recebe um IP público só seu."] : null;
    const status = { Connected: "Conectado", Disconnected: "Desconectado", Connecting: "Conectando" }[r.conexao] || r.conexao;
    pintar(parteT("conexao"), html`<dl class="ficha">
      ${r.fabricante || r.modelo ? html`<dt>Roteador</dt><dd>${[r.fabricante, r.modelo || r.nome].filter(Boolean).join(" ")}</dd>` : ""}
      ${status ? html`<dt>Situação</dt><dd>${status}${r.uptime_s ? `, há ${fmt.duracao(r.uptime_s)}` : ""}</dd>` : ""}
      ${r.ip_publico ? html`<dt>IP na internet</dt><dd class="end">${r.ip_publico}</dd>` : ""}
      ${tipo ? html`<dt>Tipo</dt><dd>${tipo[0]}<br><small class="discreto">${tipo[1]}</small></dd>` : ""}
      ${r.link_down_bps ? html`<dt>Velocidade do link</dt><dd>${fmt.bpsTexto(r.link_down_bps)} para baixar, ${fmt.bpsTexto(r.link_up_bps)} para enviar<br><small class="discreto">É o máximo da porta do roteador; o plano contratado pode ser menor.</small></dd>` : ""}
    </dl>`);
  }

  function atualizarTrafego(estado) {
    if (!raizT || !estado) return;
    pintarAviso(estado);
    pintarPlacas(estado);
    pintarConexao(estado);
    const t = estado.trafego && estado.trafego.agora ? estado.trafego.agora.ts : null;
    if (amostraVista === undefined || (t !== amostraVista && Date.now() - cargaEm > (periodo > 86400 ? 300000 : 25000))) {
      amostraVista = t;
      carregarTrafego();
    }
  }

  HN.visoes.trafego = {
    titulo: "Tráfego",
    montar: montarTrafego,
    atualizar: atualizarTrafego,
    redesenhar: desenharTrafego,
    desmontar() { raizT = null; },
  };

  // =================================================================== eventos
  const GRUPOS = [["", "Todos"], ["queda,volta", "Quedas e retornos"], ["novo,saiu,voltou", "Aparelhos"], ["alerta", "Alertas enviados"], ["sistema", "Sistema"]];
  const LIMITE = 60;
  let raizE = null, grupo = "", eventos = [], acabou = false, topoVisto;

  function montarEventos(el, estado) {
    raizE = el;
    eventos = [];
    acabou = false;
    topoVisto = undefined;
    pintar(el, html`
      <div class="visao-cabeca">
        <div><h1>Eventos</h1><p>O que aconteceu na rede, do mais recente para o mais antigo. Clique num evento para ver o aparelho.</p></div>
        <div class="acoes"><div class="segmentos" role="group" aria-label="Mostrar">${GRUPOS.map(([t, nome]) => html`<button type="button" data-grupo="${t}" aria-pressed="${t === grupo}">${nome}</button>`)}</div></div>
      </div>
      <section class="bloco"><ul class="eventos" data-parte="lista" aria-live="polite"></ul></section>
      <div class="form-acoes centro" data-parte="mais"></div>`, true);
    el.addEventListener("click", (ev) => {
      const g = ev.target.closest("[data-grupo]");
      if (g) {
        grupo = g.dataset.grupo;
        el.querySelectorAll("[data-grupo]").forEach((x) => x.setAttribute("aria-pressed", String(x === g)));
        eventos = [];
        acabou = false;
        carregarEventos();
        return;
      }
      const alvo = ev.target.closest("[data-alvo]");
      if (alvo) {
        const a = alvo.dataset.alvo;
        if (a === "internet") HN.gaveta.abrirInternet();
        else if (HN.ui.dispositivo(a.slice(12))) HN.gaveta.abrirDispositivo(a.slice(12));
        else toast("Esse aparelho não está mais no inventário.");
        return;
      }
      if (ev.target.closest("[data-acao=mais]")) carregarEventos(true);
    });
    atualizarEventos(estado);
  }

  async function carregarEventos(mais) {
    const params = new URLSearchParams({ limite: String(LIMITE) });
    if (grupo) params.set("tipos", grupo);
    if (mais && eventos.length) params.set("antes", String(eventos[eventos.length - 1].id));
    let pagina;
    try {
      pagina = await HN.api("GET", `/api/eventos?${params}`);
    } catch (e) {
      if (raizE) pintar(raizE.querySelector("[data-parte=lista]"), html`<li>${HN.ui.vazio("Não consegui carregar os eventos", e.message)}</li>`);
      return;
    }
    if (!raizE) return;
    const primeiraCarga = !eventos.length;
    const porId = new Map(eventos.map((e) => [e.id, e]));
    pagina.forEach((e) => porId.set(e.id, e));
    eventos = [...porId.values()].sort((a, b) => b.id - a.id);
    if (mais || primeiraCarga) acabou = pagina.length < LIMITE;
    pintarEventos();
  }

  function pintarEventos() {
    const lista = raizE.querySelector("[data-parte=lista]");
    if (!eventos.length) {
      pintar(lista, html`<li>${HN.ui.vazio(grupo ? "Nenhum evento deste tipo" : "Nada aconteceu ainda", "Quedas, retornos, aparelhos novos e alertas enviados aparecem aqui.")}</li>`);
    } else {
      let dia = null;
      const partes = [];
      eventos.forEach((e) => {
        const d = fmt.diaLongo(e.ts);
        if (d !== dia) { dia = d; partes.push(html`<li class="dia-eventos">${d}</li>`); }
        const clicavel = e.alvo && (e.alvo === "internet" || e.alvo.startsWith("dispositivo:"));
        partes.push(html`<li class="evento" data-gravidade="${e.gravidade}">
          <time datetime="${new Date(e.ts * 1000).toISOString()}">${fmt.hora(e.ts)}</time>
          <span class="marcador" aria-hidden="true"></span>
          <div>${clicavel ? html`<button type="button" class="link-evento" data-alvo="${e.alvo}">${e.titulo}</button>` : html`<b>${e.titulo}</b>`}${e.detalhe ? html`<small>${e.detalhe}</small>` : ""}</div>
        </li>`);
      });
      pintar(lista, partes);
    }
    pintar(raizE.querySelector("[data-parte=mais]"), !acabou && eventos.length >= LIMITE
      ? html`<button type="button" class="botao" data-acao="mais">Carregar mais antigos</button>` : "");
  }

  function atualizarEventos(estado) {
    if (!raizE || !estado) return;
    const topo = estado.eventos && estado.eventos[0] ? estado.eventos[0].id : null;
    if (topo !== topoVisto) {
      topoVisto = topo;
      carregarEventos();
    }
  }

  HN.visoes.eventos = {
    titulo: "Eventos",
    montar: montarEventos,
    atualizar: atualizarEventos,
    desmontar() { raizE = null; },
  };
})(window.HN = window.HN || {});
