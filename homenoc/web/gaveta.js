/* HomeNOC: gaveta de detalhes. Abre ao clicar num aparelho (no mapa, na lista,
   no painel ou num evento), na internet ou num salto do caminho até ela. */
"use strict";
(function (HN) {
  const { fmt, graficos } = HN;
  const { html, cru, pintar, icone, glifo, situacao, nomePorta, toast, ocupado, alternar, roteadorDe } = HN.ui;

  let aberto = null;             // { tipo: "dispositivo" | "internet" | "salto", id, no }
  let focoAnterior = null;
  let historicoEm = 0;
  let cicloVisto = null;

  const raiz = () => document.getElementById("gaveta");
  const painel = () => document.getElementById("gaveta-painel");
  const parte = (nome) => painel().querySelector(`[data-parte="${nome}"]`);
  const agora = () => (HN.S.estado ? HN.S.estado.agora : Date.now() / 1000);

  // ------------------------------------------------------------------ abrir e fechar
  function mostrar(conteudo, info) {
    const jaAberta = Boolean(aberto);
    if (!jaAberta) focoAnterior = document.activeElement;
    aberto = info;
    historicoEm = 0;
    pintar(painel(), conteudo, true);
    painel().scrollTop = 0;
    raiz().hidden = false;
    document.getElementById("app").inert = true;
    if (!jaAberta && !(history.state && history.state.gaveta)) {
      try { history.pushState({ gaveta: true }, ""); } catch (e) { /* sem histórico: o botão Voltar só não fecha a gaveta */ }
    }
    const botaoFechar = painel().querySelector(".botao-fechar");
    if (botaoFechar) botaoFechar.focus({ preventScroll: true });
  }

  function fechar(peloHistorico) {
    if (!aberto) return;
    aberto = null;
    raiz().hidden = true;
    document.getElementById("app").inert = false;
    pintar(painel(), "", true);
    if (!peloHistorico && history.state && history.state.gaveta) history.back();
    if (focoAnterior && focoAnterior.isConnected) focoAnterior.focus({ preventScroll: true });
    if (HN.visaoAtual && HN.visaoAtual.aoFecharGaveta) HN.visaoAtual.aoFecharGaveta();
  }

  function cabeca(glifoTipo, titulo, selos) {
    return html`<div class="gaveta-cabeca">
      <span class="icone-tipo">${glifo(glifoTipo)}</span>
      <div><h2 id="gaveta-titulo">${titulo}</h2><div class="selos" data-parte="selos">${selos}</div></div>
      <button type="button" class="botao-fechar" data-fechar aria-label="Fechar detalhes">${icone("fechar")}</button>
    </div>`;
  }

  const linhaFicha = (rotulo, valor, nota) => (valor == null || valor === "") ? "" :
    html`<dt>${rotulo}</dt><dd>${valor}${nota ? html`<br><small class="discreto">${nota}</small>` : ""}</dd>`;

  // ------------------------------------------------------------------ aparelho
  function selosAparelho(d) {
    const s = situacao(d);
    const partes = [html`<span class="estado" data-estado="${s.estado}">${s.texto}${d.online && d.latencia != null ? `, ${fmt.ms(d.latencia)}` : ""}</span>`,
      html`<span class="selo">${d.tipo_nome}</span>`];
    if (d.alertar && !d.este_pc) partes.push(html`<span class="selo">Monitorado</span>`);
    if (HN.ui.novo(d, agora())) partes.push(html`<span class="selo">Novo na rede</span>`);
    return partes;
  }

  function parteMonitorar(d) {
    if (d.este_pc) {
      return html`<h3>Monitoramento</h3><p class="dica">Este é o computador onde o HomeNOC está rodando. Para saber se ele desligar ou travar, use o Healthchecks.io em <a href="#ajustes/alertas" data-fechar-e-ir>Ajustes</a>.</p>`;
    }
    const semPing = !d.responde_ping && d.online;
    return html`<h3>Monitoramento</h3>
      ${alternar({ nome: "alertar", marcado: d.alertar, titulo: "Avisar quando cair", descricao: "Testa o aparelho a cada minuto e avisa quando ele para de responder e quando volta." })}
      ${semPing ? html`<p class="dica">Este aparelho não responde a ping: foi encontrado pela tabela ARP do computador. Se ligar o aviso, ele pode aparecer como fora do ar mesmo ligado.</p>` : ""}`;
  }

  function parteIdentificacao(d) {
    const motivo = (d.motivos || [])[0];
    const u = d.upnp || {};
    const mac = d.mac ? (d.mac_aleatorio ? html`${d.mac}<br><small class="discreto">Aleatório: recurso de privacidade de celulares e notebooks</small>` : d.mac) : "Desconhecido";
    return html`
      ${linhaFicha("Tipo", d.tipo_nome, motivo ? `Pista: ${motivo}` : "")}
      ${linhaFicha("Endereço IP", d.ip)}
      <dt>Endereço MAC</dt><dd>${mac}</dd>
      ${linhaFicha("Fabricante", d.mac_aleatorio ? "" : d.fabricante)}
      ${linhaFicha("Nome na rede", d.nome_dns)}
      ${linhaFicha("Anúncio UPnP", u.nome ? [u.nome, u.modelo && u.modelo !== u.nome ? ` (${u.modelo})` : ""].join("") : "", u.fabricante && u.fabricante !== d.fabricante ? u.fabricante : "")}
      ${linhaFicha("Sistema provável", d.so, d.ttl ? `TTL recebido: ${d.ttl}` : "")}
      ${linhaFicha("Responde a ping", d.responde_ping ? "Sim" : "Não, encontrado pela tabela ARP")}
      ${linhaFicha("Primeira vez", d.primeira_vez ? fmt.dataHora(d.primeira_vez) : "")}
      ${linhaFicha(d.online ? "Na rede desde" : "Visto por último", d.online ? (d.mudou_em ? `${fmt.dataHora(d.mudou_em)} (${fmt.ha(d.mudou_em, agora())})` : "") : (d.ultima_vez ? `${fmt.dataHora(d.ultima_vez)} (${fmt.ha(d.ultima_vez, agora())})` : ""))}`;
  }

  function partePortas(d) {
    const portas = d.portas;
    const web = (portas || []).find((p) => [80, 443, 8080, 8443].includes(p));
    const url = web ? `${web === 443 || web === 8443 ? "https" : "http"}://${d.ip}${[80, 443].includes(web) ? "" : `:${web}`}` : null;
    let lista;
    if (d.escaneando) lista = html`<p class="dica">Testando as portas, leva alguns segundos…</p>`;
    else if (portas == null) lista = html`<p class="dica">Ainda não testadas.</p>`;
    else if (!portas.length) lista = html`<p class="dica">Nenhuma das 20 portas comuns está aberta.</p>`;
    else lista = html`<div class="portas-abertas">${portas.map((p) => html`<span><b>${p}</b>${nomePorta(p)}</span>`)}</div>`;
    return html`<h3>Portas abertas</h3>${lista}
      ${d.portas_em && !d.escaneando ? html`<small class="dica">Testadas ${fmt.ha(d.portas_em, agora())}. Só portas comuns, e só na sua rede.</small>` : ""}
      <div class="form-acoes">
        <button type="button" class="botao pequeno${d.escaneando ? " girando" : ""}" data-acao="portas" ${d.escaneando || !d.ip ? cru("disabled") : ""}>${icone("varrer")}${d.escaneando ? "Testando…" : "Testar portas agora"}</button>
        ${url ? html`<a class="botao pequeno" href="${url}" target="_blank" rel="noopener noreferrer">${icone("abrir")}${d.tipo === "roteador" ? "Abrir a página do roteador" : "Abrir a página do aparelho"}</a>` : ""}
      </div>`;
  }

  function parteZabbix(d, estado) {
    const z = d.zabbix;
    if (!z) {
      return estado && estado.zabbix && estado.zabbix.configurado && estado.zabbix.ok
        ? html`<h3>Zabbix</h3><p class="dica">Este aparelho não está cadastrado no Zabbix.</p>` : "";
    }
    const ping = z.ping == null ? "Sem dados" : z.ping ? "Respondendo" : "Sem resposta";
    return html`<h3>Zabbix</h3><dl class="ficha">
      ${linhaFicha("Nome no Zabbix", z.nome)}
      <dt>Ping do Zabbix</dt><dd><span class="estado" data-estado="${z.ping == null ? "off" : z.ping ? "ok" : "critico"}">${ping}</span></dd>
      <dt>Problemas</dt><dd>${z.problemas && z.problemas.length ? html`<ul class="lista-simples">${z.problemas.map((p) => html`<li><span class="estado" data-estado="alerta">${p}</span></li>`)}</ul>` : "Nenhum ativo"}</dd>
    </dl>`;
  }

  function abrirDispositivo(id) {
    const d = HN.ui.dispositivo(id);
    if (!d) return;
    mostrar(html`
      ${cabeca(d.tipo, d.nome, selosAparelho(d))}
      <section class="secao">
        <h3>Nome</h3>
        <form class="apelido" data-form="apelido">
          <input class="busca" type="text" name="apelido" maxlength="40" autocomplete="off" value="${d.apelido || ""}" placeholder="${d.nome}" aria-label="Apelido do aparelho">
          <button class="botao" type="submit">Salvar</button>
        </form>
        <small class="dica">Dê um nome fácil de reconhecer. Ele aparece no mapa e nos alertas.</small>
      </section>
      <section class="secao" data-parte="monitorar">${parteMonitorar(d)}</section>
      <section class="secao">
        <h3>Tempo de resposta nas últimas 24 horas</h3>
        <div data-parte="historico"><p class="dica">Carregando…</p></div>
      </section>
      <section class="secao"><h3>Identificação</h3><dl class="ficha" data-parte="identificacao">${parteIdentificacao(d)}</dl></section>
      <section class="secao" data-parte="portas">${partePortas(d)}</section>
      <section class="secao" data-parte="zabbix">${parteZabbix(d, HN.S.estado)}</section>
    `, { tipo: "dispositivo", id });
    carregarHistorico(`dispositivo:${id}`);
  }

  async function carregarHistorico(alvo) {
    historicoEm = Date.now();
    const alvoAberto = aberto;
    let dados;
    try {
      dados = await HN.api("GET", `/api/historico?alvo=${encodeURIComponent(alvo)}&periodo=86400`);
    } catch (e) {
      if (aberto === alvoAberto && parte("historico")) pintar(parte("historico"), html`<p class="dica">${e.message}</p>`, true);
      return;
    }
    const caixa = parte("historico");
    if (aberto !== alvoAberto || !caixa) return;
    const est = dados.estatisticas || {};
    const passo = (dados.ate - dados.desde) / 240;
    caixa.innerHTML = '<div data-grafico></div><dl class="ficha ficha-estatisticas"></dl>';
    graficos.linhas(caixa.querySelector("[data-grafico]"), {
      series: [{ nome: "Tempo de resposta", cor: "var(--s1)", area: true, pontos: dados.serie.map((p) => [p[0], p[1]]) }],
      perdas: dados.serie.map((p) => [p[0], p[2]]),
      t0: dados.desde, t1: dados.ate, altura: 150, lacuna: passo * 4, unidade: "ms", padraoY: 50,
      dicaY: fmt.ms, rotulo: "Tempo de resposta nas últimas 24 horas",
      vazio: "Os pontos aparecem a cada varredura (ou a cada minuto, se o aviso estiver ligado).",
    });
    pintar(caixa.querySelector(".ficha"), est.amostras ? html`
      ${est.media != null ? html`<dt>Média</dt><dd>${fmt.ms(est.media)} <small class="discreto">(mín. ${fmt.ms(est.minimo)}, máx. ${fmt.ms(est.maximo)})</small></dd>` : ""}
      <dt>Respondeu</dt><dd>${fmt.pct(est.disponibilidade)} dos testes <small class="discreto">(${est.amostras} testes)</small></dd>` : "");
  }

  // ------------------------------------------------------------------ internet
  function selosInternet(estado) {
    const i = estado && estado.internet;
    if (!i) return html`<span class="estado" data-estado="off">Aguardando o primeiro teste</span>`;
    const tempo = i.desde ? estado.agora - i.desde : null;
    const selo = tempo == null ? "" : tempo < 60 ? (i.online ? "Acabou de voltar" : "Caiu agora")
      : `${i.online ? "Sem quedas há" : "Fora há"} ${fmt.duracao(tempo)}`;
    return html`<span class="estado" data-estado="${i.online ? "ok" : "critico"}">${i.online ? `No ar, ${fmt.ms(i.ms)}` : "Fora do ar"}</span>
      ${selo ? html`<span class="selo">${selo}</span>` : ""}`;
  }

  function parteServidores(estado) {
    const i = estado && estado.internet;
    if (!i) return html`<p class="dica">O primeiro teste acontece logo depois que o HomeNOC abre.</p>`;
    return html`<ul class="lista-simples">${i.servidores.map((s) => html`<li><span class="estado" data-estado="${s.online ? "ok" : "critico"}">${s.nome}</span> <span class="discreto">${s.host}</span> <b class="end">${s.online ? fmt.ms(s.ms) : "sem resposta"}</b></li>`)}</ul>
      <small class="dica">A internet só é considerada fora do ar quando nenhum deles responde.</small>`;
  }

  function parteCaminho(estado) {
    const caminho = (estado && estado.caminho) || [];
    if (!caminho.length) return html`<p class="dica">O caminho aparece depois da primeira varredura.</p>`;
    const gw = estado.rede && estado.rede.gateway;
    return html`<ol class="caminho">${caminho.map((s) => {
      const papel = s.ip === gw || s.salto === 1 ? "Seu roteador" : (s.ip === "8.8.8.8" || s.ip === "1.1.1.1") ? "Destino" : HN.mapa.papelSalto(s.ip);
      return html`<li><b>${papel}</b> <span class="discreto">${s.ip || "não respondeu"}</span>${s.ms != null ? html` <span class="end">${fmt.ms(s.ms)}</span>` : ""}</li>`;
    })}</ol>`;
  }

  function parteConexao(estado) {
    const r = estado && estado.trafego && estado.trafego.roteador;
    if (!r) return "";
    const tipo = r.cgnat ? "CGNAT: o IP público é compartilhado com outros clientes da operadora"
      : r.nat_duplo ? "NAT duplo: há outro roteador ou modem antes do seu" : r.ip_publico ? "IP público próprio" : "";
    const link = r.link_down_bps ? `${fmt.bpsTexto(r.link_down_bps)} para baixar, ${fmt.bpsTexto(r.link_up_bps)} para enviar` : "";
    return html`<h3>Sua conexão</h3><dl class="ficha">
      ${linhaFicha("IP público", r.ip_publico, tipo)}
      ${linhaFicha("Conectado há", r.uptime_s ? fmt.duracao(r.uptime_s) : "")}
      ${linhaFicha("Velocidade do link", link, link ? "Informada pelo roteador" : "")}
    </dl>`;
  }

  function abrirInternet() {
    const estado = HN.S.estado;
    mostrar(html`
      ${cabeca("internet", "Internet", selosInternet(estado))}
      <section class="secao"><h3>Servidores testados</h3><div data-parte="servidores">${parteServidores(estado)}</div></section>
      <section class="secao"><h3>Tempo de resposta nas últimas 24 horas</h3><div data-parte="historico"><p class="dica">Carregando…</p></div></section>
      <section class="secao" data-parte="conexao">${parteConexao(estado)}</section>
      <section class="secao"><h3>Caminho até a internet</h3>${parteCaminho(estado)}</section>
    `, { tipo: "internet" });
    carregarHistorico("internet");
  }

  // ------------------------------------------------------------------ salto do caminho
  const EXPLICACOES = {
    "Modem/ONT ou 2º roteador": "Um endereço privado depois do seu roteador: normalmente é o modem ou a ONT da operadora. Dois roteadores em sequência (NAT duplo) podem atrapalhar jogos online e o acesso de fora de casa.",
    "CGNAT da operadora": "Endereço da faixa 100.64.0.0/10: a operadora divide um IP público entre vários clientes (CGNAT). É comum em fibra e 4G e impede abrir portas para acessar a sua casa de fora.",
    "Rede da operadora": "Um roteador da operadora (ou de quem ela contrata) no caminho até a internet. Atrasos que começam aqui não são culpa da sua rede.",
    "Sem resposta": "Este ponto do caminho não respondeu ao traceroute. É normal: muitos roteadores de operadora ignoram esse tipo de teste.",
  };

  function abrirSalto(no) {
    if (no.tipo === "internet") return abrirInternet();
    const s = no.salto || {};
    mostrar(html`
      ${cabeca("salto", no.papel, html`<span class="selo">Salto ${s.salto}</span>${s.ms != null ? html`<span class="selo">${fmt.ms(s.ms)}</span>` : ""}`)}
      <section class="secao"><h3>O que é</h3><p>${EXPLICACOES[no.papel] || ""}</p></section>
      <section class="secao"><h3>Detalhes</h3><dl class="ficha">
        ${linhaFicha("Endereço IP", s.ip || "Não respondeu")}
        ${linhaFicha("Tempo de resposta", s.ms != null ? fmt.ms(s.ms) : "")}
        ${linhaFicha("Posição", `${s.salto}º salto a partir deste computador`)}
      </dl></section>
      <section class="secao"><h3>Caminho completo</h3>${parteCaminho(HN.S.estado)}</section>
    `, { tipo: "salto", id: no.id, no });
  }

  // ------------------------------------------------------------------ atualização periódica
  function atualizar(estado) {
    if (!aberto) return;
    const ciclo = estado.monitor && estado.monitor.ultimo_ciclo;
    const recarregar = ciclo !== cicloVisto && Date.now() - historicoEm > 55000;
    cicloVisto = ciclo;
    if (aberto.tipo === "dispositivo") {
      const d = estado.dispositivos.find((x) => x.id === aberto.id);
      if (!d) return fechar();
      pintar(parte("selos"), selosAparelho(d));
      const caixa = painel().querySelector("input[name=alertar]");
      if (!caixa || (!caixa.dataset.enviando && caixa.checked !== Boolean(d.alertar))) pintar(parte("monitorar"), parteMonitorar(d));
      pintar(parte("identificacao"), parteIdentificacao(d));
      const foco = document.activeElement;
      if (!parte("portas").contains(foco)) pintar(parte("portas"), partePortas(d));
      pintar(parte("zabbix"), parteZabbix(d, estado));
      if (recarregar) carregarHistorico(`dispositivo:${d.id}`);
    } else if (aberto.tipo === "internet") {
      pintar(parte("selos"), selosInternet(estado));
      pintar(parte("servidores"), parteServidores(estado));
      pintar(parte("conexao"), parteConexao(estado));
      if (recarregar) carregarHistorico("internet");
    }
  }

  // ------------------------------------------------------------------ eventos da gaveta
  function ligar() {
    const r = raiz();
    r.addEventListener("click", (ev) => {
      const ir = ev.target.closest("[data-fechar-e-ir]");
      if (ir) {
        ev.preventDefault();
        const destino = ir.getAttribute("href");
        fechar(true);
        history.replaceState(null, "", destino);
        window.dispatchEvent(new HashChangeEvent("hashchange"));
        return;
      }
      if (ev.target.closest("[data-fechar]")) fechar();
      const botao = ev.target.closest("[data-acao=portas]");
      if (botao && aberto && aberto.tipo === "dispositivo") escanearPortas(botao);
    });
    r.addEventListener("submit", async (ev) => {
      const form = ev.target.closest("[data-form=apelido]");
      if (!form || !aberto) return;
      ev.preventDefault();
      const id = aberto.id, campo = form.elements.apelido, botao = form.querySelector("button");
      try {
        const d = await ocupado(botao, "Salvando…", () => HN.api("POST", `/api/dispositivos/${encodeURIComponent(id)}`, { apelido: campo.value }));
        toast(d.apelido ? `Nome salvo: ${d.apelido}` : "Apelido removido");
        const titulo = document.getElementById("gaveta-titulo");
        if (titulo && aberto && aberto.id === id) titulo.textContent = d.nome;
        campo.placeholder = d.nome;
        HN.app.atualizarJa();
      } catch (e) { toast(e.message, 5000); }
    });
    r.addEventListener("change", async (ev) => {
      const caixa = ev.target.closest("input[name=alertar]");
      if (!caixa || !aberto) return;
      const id = aberto.id, valor = caixa.checked;
      caixa.dataset.enviando = "1";
      try {
        await HN.api("POST", `/api/dispositivos/${encodeURIComponent(id)}`, { alertar: valor });
        toast(valor ? "Pronto: você será avisado se ele cair." : "Aviso desligado para este aparelho.");
        HN.app.atualizarJa();
      } catch (e) {
        caixa.checked = !valor;
        toast(e.message, 5000);
      } finally { delete caixa.dataset.enviando; }
    });
    r.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") { ev.preventDefault(); fechar(); }
    });
    window.addEventListener("popstate", () => { if (aberto) fechar(true); });
  }

  async function escanearPortas(botao) {
    const id = aberto.id;
    try {
      await ocupado(botao, "Testando…", () => HN.api("POST", `/api/dispositivos/${encodeURIComponent(id)}/portas`));
      const d = HN.ui.dispositivo(id);
      if (d) { d.escaneando = true; if (aberto && aberto.id === id) pintar(parte("portas"), partePortas(d)); }
      HN.app.atualizarJa();
    } catch (e) { toast(e.message, 5000); }
  }

  HN.gaveta = {
    abrirDispositivo, abrirInternet, abrirSalto, fechar, atualizar, ligar,
    abrirRoteador() { const r = roteadorDe(HN.S.estado); if (r) abrirDispositivo(r.id); else abrirInternet(); },
    get aberta() { return aberto; },
  };
})(window.HN = window.HN || {});
