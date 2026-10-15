/* HomeNOC: as duas visões do inventário da rede: o mapa (topologia) e a lista
   de aparelhos. As duas abrem a mesma gaveta de detalhes. */
"use strict";
(function (HN) {
  const { fmt } = HN;
  const { html, cru, pintar, icone, glifo, situacao, alternar, toast, ocupado } = HN.ui;

  async function varrerAgora(botao) {
    try {
      await ocupado(botao, "Iniciando…", () => HN.api("POST", "/api/varrer"));
      toast("Varredura iniciada. Leva cerca de um minuto.");
      HN.app.atualizarJa();
    } catch (e) { toast(e.message, 5000); }
  }

  function pintarBotaoVarrer(botao, estado) {
    if (!botao) return;
    const v = (estado && estado.varredura) || {};
    botao.disabled = Boolean(v.ativa);
    botao.classList.toggle("girando", Boolean(v.ativa));
    pintar(botao, html`${icone("varrer")}${v.ativa ? `Varrendo… ${v.progresso || 0}%` : "Varrer agora"}`);
  }

  // =================================================================== mapa
  let mapa = null, raizMapa = null;

  const LEGENDA = html`
    <span><svg viewBox="0 0 18 12" aria-hidden="true"><circle cx="9" cy="6" r="4.5" fill="none" stroke="var(--good)" stroke-width="2"/></svg>Na rede</span>
    <span><svg viewBox="0 0 18 12" aria-hidden="true"><circle cx="9" cy="6" r="4.5" fill="none" stroke="var(--off)" stroke-width="2" stroke-dasharray="2 2"/></svg>Fora da rede</span>
    <span><svg viewBox="0 0 18 12" aria-hidden="true"><circle cx="9" cy="6" r="4.5" fill="none" stroke="var(--critical)" stroke-width="2.4"/></svg>Sem resposta ou com problema</span>
    <span><svg viewBox="0 0 18 12" aria-hidden="true"><circle cx="9" cy="6" r="3.5" fill="var(--accent)"/></svg>Avisa quando cai</span>
    <span><svg viewBox="0 0 18 12" aria-hidden="true"><path d="M1 6h16" stroke="var(--accent)" stroke-width="2"/></svg>Caminho até a internet</span>
    <small class="discreto">Quanto mais longe do roteador, maior o tempo de resposta.</small>`;

  function montarMapa(el, estado) {
    raizMapa = el;
    const mostrarOff = HN.ui.ler("mapa.desconectados", "1") === "1";
    pintar(el, html`
      <div class="visao-cabeca">
        <div><h1>Mapa da rede</h1><p data-parte="sub"></p></div>
        <div class="acoes">
          <button type="button" class="botao" data-acao="reorganizar">${icone("centralizar")}Reorganizar</button>
          <button type="button" class="botao primario" data-acao="varrer"></button>
        </div>
      </div>
      <section class="bloco">
        <div class="bloco-corpo barra-ferramentas">
          <input class="busca" type="search" placeholder="Procurar no mapa" aria-label="Procurar no mapa por nome, IP ou fabricante" data-parte="busca">
          ${alternar({ nome: "desconectados", marcado: mostrarOff, titulo: "Mostrar quem está fora da rede" })}
        </div>
        <div class="mapa-envoltorio">
          <div class="mapa-alvo" data-parte="mapa"></div>
          <div class="mapa-dica" aria-hidden="true">Arraste para mover. Use a roda do mouse ou dois dedos para aproximar.</div>
          <div class="mapa-zoom"><button type="button" data-zoom="1.25" aria-label="Aproximar">+</button><button type="button" data-zoom="0.8" aria-label="Afastar">−</button></div>
        </div>
        <div class="mapa-legenda">${LEGENDA}</div>
      </section>`, true);
    mapa = HN.mapa.criar(el.querySelector("[data-parte=mapa]"), {
      aoSelecionar: (id) => { if (id) HN.gaveta.abrirDispositivo(id); },
      aoSelecionarSalto: (no) => HN.gaveta.abrirSalto(no),
    });
    mapa.mostrarOffline(mostrarOff);
    el.addEventListener("click", (ev) => {
      const z = ev.target.closest("[data-zoom]");
      if (z) { mapa.zoom(Number(z.dataset.zoom)); return; }
      const b = ev.target.closest("[data-acao]");
      if (!b) return;
      if (b.dataset.acao === "reorganizar") mapa.reorganizar();
      if (b.dataset.acao === "varrer") varrerAgora(b);
    });
    el.querySelector("[data-parte=busca]").addEventListener("input", (ev) => mapa.filtrar(ev.target.value));
    el.querySelector("input[name=desconectados]").addEventListener("change", (ev) => {
      HN.ui.gravar("mapa.desconectados", ev.target.checked ? "1" : "0");
      mapa.mostrarOffline(ev.target.checked);
    });
    atualizarMapa(estado);
  }

  function atualizarMapa(estado) {
    if (!raizMapa || !estado) return;
    mapa.atualizar(estado);
    const ds = estado.dispositivos || [];
    const online = ds.filter((d) => d.online).length;
    const rede = estado.rede && estado.rede.rede;
    pintar(raizMapa.querySelector("[data-parte=sub]"), ds.length
      ? `${rede ? `Rede ${rede}, ` : ""}${online} ${online === 1 ? "aparelho conectado" : "aparelhos conectados"}. Clique em um aparelho para ver tudo sobre ele.`
      : "Procurando aparelhos na rede…");
    pintarBotaoVarrer(raizMapa.querySelector("[data-acao=varrer]"), estado);
  }

  HN.visoes.mapa = {
    titulo: "Mapa",
    montar: montarMapa,
    atualizar: atualizarMapa,
    aoFecharGaveta() { if (mapa) mapa.selecionar(null); },
    desmontar() { if (mapa) mapa.destruir(); mapa = null; raizMapa = null; },
  };

  // =================================================================== aparelhos
  let raizLista = null;
  const filtros = { estado: "todos", tipo: "", busca: "", ordem: "padrao", direcao: 1 };
  const FILTROS = [
    ["todos", "Todos", () => true],
    ["online", "Na rede", (d) => d.online],
    ["offline", "Fora", (d) => !d.online],
    ["monitorados", "Monitorados", (d) => d.alertar && !d.este_pc],
    ["novos", "Novos", (d, agora) => HN.ui.novo(d, agora)],
  ];
  const ipNumero = (ip) => (ip || "255.255.255.255").split(".").reduce((n, p) => n * 256 + Number(p), 0);
  const ORDENS = {
    nome: (a, b) => a.nome.localeCompare(b.nome, "pt-BR", { sensitivity: "base" }),
    ip: (a, b) => ipNumero(a.ip) - ipNumero(b.ip),
    latencia: (a, b) => (a.latencia == null) - (b.latencia == null) || (a.latencia || 0) - (b.latencia || 0),
    visto: (a, b) => (b.online - a.online) || (b.ultima_vez || 0) - (a.ultima_vez || 0),
  };

  function montarLista(el, estado) {
    raizLista = el;
    pintar(el, html`
      <div class="visao-cabeca">
        <div><h1>Aparelhos</h1><p data-parte="sub"></p></div>
        <div class="acoes">
          <button type="button" class="botao" data-acao="csv">${icone("baixar")}Exportar CSV</button>
          <button type="button" class="botao primario" data-acao="varrer"></button>
        </div>
      </div>
      <section class="bloco">
        <div class="bloco-corpo barra-ferramentas">
          <input type="search" class="busca" placeholder="Nome, IP, MAC ou fabricante" aria-label="Procurar aparelhos" data-parte="busca" value="${filtros.busca}">
          <div class="segmentos" role="group" aria-label="Mostrar" data-parte="filtros"></div>
          <select class="busca seletor" aria-label="Tipo de aparelho" data-parte="tipo"></select>
        </div>
        <div class="tabela-rolagem">
          <table class="tabela">
            <caption class="sr">Aparelhos encontrados na rede</caption>
            <thead><tr data-parte="cabecalho"></tr></thead>
            <tbody data-parte="linhas"></tbody>
          </table>
        </div>
      </section>`, true);
    el.addEventListener("click", aoClicarLista);
    el.addEventListener("keydown", (ev) => {
      const linha = ev.target.closest("tr[data-id]");
      if (linha && ev.target === linha && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); HN.gaveta.abrirDispositivo(linha.dataset.id); }
    });
    el.addEventListener("change", aoMudarLista);
    el.querySelector("[data-parte=busca]").addEventListener("input", (ev) => { filtros.busca = ev.target.value; pintarLista(HN.S.estado); });
    atualizarLista(estado);
  }

  function aoClicarLista(ev) {
    if (ev.target.closest(".alternar")) return;           // a chave "avisar" não abre a gaveta
    const acao = ev.target.closest("[data-acao]");
    if (acao) {
      if (acao.dataset.acao === "csv") HN.ui.exportarCsv();
      if (acao.dataset.acao === "varrer") varrerAgora(acao);
      return;
    }
    const filtro = ev.target.closest("[data-filtro]");
    if (filtro) { filtros.estado = filtro.dataset.filtro; pintarLista(HN.S.estado); return; }
    const ordem = ev.target.closest("[data-ordem]");
    if (ordem) {
      const col = ordem.dataset.ordem;
      if (filtros.ordem === col) filtros.direcao *= -1;
      else { filtros.ordem = col; filtros.direcao = 1; }
      pintarLista(HN.S.estado);
      return;
    }
    const linha = ev.target.closest("tr[data-id]");
    if (linha) HN.gaveta.abrirDispositivo(linha.dataset.id);
  }

  async function aoMudarLista(ev) {
    if (ev.target.matches("[data-parte=tipo]")) { filtros.tipo = ev.target.value; pintarLista(HN.S.estado); return; }
    const caixa = ev.target.closest("input[name=alertar]");
    if (!caixa) return;
    const id = caixa.closest("tr[data-id]").dataset.id, valor = caixa.checked;
    const d = HN.ui.dispositivo(id);
    caixa.disabled = true;
    try {
      await HN.api("POST", `/api/dispositivos/${encodeURIComponent(id)}`, { alertar: valor });
      if (d) d.alertar = valor;
      toast(valor ? `Você será avisado se ${d ? d.nome : "o aparelho"} cair.` : `Aviso desligado para ${d ? d.nome : "o aparelho"}.`);
      HN.app.atualizarJa();
    } catch (e) {
      caixa.checked = !valor;
      toast(e.message, 5000);
    } finally { caixa.disabled = false; }
  }

  function cabecalho() {
    const th = (col, texto, classe) => {
      const ativo = filtros.ordem === col;
      const sort = ativo ? (filtros.direcao > 0 ? "ascending" : "descending") : null;
      return html`<th scope="col" class="${classe || ""}" ${sort ? cru(`aria-sort="${sort}"`) : ""}><button type="button" class="ordenar" data-ordem="${col}">${texto}${ativo ? (filtros.direcao > 0 ? " ↑" : " ↓") : ""}</button></th>`;
    };
    return html`${th("nome", "Aparelho")}<th scope="col">Situação</th>${th("ip", "IP")}<th scope="col" class="col-extra">MAC e fabricante</th>${th("latencia", "Resposta", "col-extra direita")}${th("visto", "Visto", "col-extra")}<th scope="col">Avisar se cair</th>`;
  }

  function linha(d, agora) {
    const s = situacao(d);
    const fab = d.mac_aleatorio ? "MAC aleatório" : d.fabricante;
    const visto = d.online ? "Agora" : d.ultima_vez ? fmt.ha(d.ultima_vez, agora) : "–";
    const extra = [d.tipo_nome, HN.ui.novo(d, agora) ? "novo" : ""].filter(Boolean).join(", ");
    return html`<tr data-id="${d.id}" tabindex="0" aria-label="${d.nome}, ${s.texto}">
      <td class="col-nome"><div class="nome-celula"><span class="icone-tipo">${glifo(d.tipo)}</span><div><b>${d.nome}</b><small>${extra}</small></div></div></td>
      <td class="col-estado"><span class="estado" data-estado="${s.estado}">${s.texto}</span></td>
      <td class="col-ip end">${d.ip || "–"}</td>
      <td class="col-extra"><span class="end">${d.mac || "–"}</span>${fab ? html`<small class="discreto bloco-texto">${fab}</small>` : ""}</td>
      <td class="col-extra direita end">${d.online && d.latencia != null && !d.este_pc ? fmt.ms(d.latencia) : "–"}</td>
      <td class="col-extra">${visto}</td>
      <td class="col-alertar">${d.este_pc ? html`<small class="discreto">Este PC</small>` : alternar({ nome: "alertar", marcado: d.alertar, rotulo: `Avisar se ${d.nome} cair` })}</td>
    </tr>`;
  }

  function pintarLista(estado) {
    if (!raizLista || !estado) return;
    const agora = estado.agora;
    const todos = estado.dispositivos || [];
    const termo = filtros.busca.trim().toLowerCase();
    const contagem = Object.fromEntries(FILTROS.map(([id, , f]) => [id, todos.filter((d) => f(d, agora)).length]));
    pintar(raizLista.querySelector("[data-parte=filtros]"), FILTROS.map(([id, nome]) =>
      html`<button type="button" data-filtro="${id}" aria-pressed="${filtros.estado === id}">${nome} <span class="discreto">${contagem[id]}</span></button>`));
    const tipos = [...new Map(todos.map((d) => [d.tipo, d.tipo_nome])).entries()].sort((a, b) => a[1].localeCompare(b[1], "pt-BR"));
    if (filtros.tipo && !tipos.some(([t]) => t === filtros.tipo)) filtros.tipo = "";
    const seletor = raizLista.querySelector("[data-parte=tipo]");
    pintar(seletor, html`<option value="">Todos os tipos</option>${tipos.map(([t, nome]) => html`<option value="${t}">${nome}</option>`)}`);
    seletor.value = filtros.tipo;
    pintar(raizLista.querySelector("[data-parte=cabecalho]"), cabecalho());

    const filtro = FILTROS.find((f) => f[0] === filtros.estado)[2];
    let lista = todos.filter((d) => filtro(d, agora) && (!filtros.tipo || d.tipo === filtros.tipo) &&
      (!termo || [d.nome, d.ip, d.mac, d.fabricante, d.nome_dns, d.tipo_nome, d.apelido].join(" ").toLowerCase().includes(termo)));
    if (filtros.ordem !== "padrao") lista = [...lista].sort((a, b) => ORDENS[filtros.ordem](a, b) * filtros.direcao);
    const corpo = raizLista.querySelector("[data-parte=linhas]");
    HN.ui.preservarFoco(corpo, () => pintar(corpo, lista.length ? lista.map((d) => linha(d, agora))
      : html`<tr><td colspan="7">${todos.length ? HN.ui.vazio("Nenhum aparelho com esses filtros", "Mude a busca ou o filtro acima.") : HN.ui.vazio("Procurando aparelhos…", "A primeira varredura leva cerca de um minuto.")}</td></tr>`));
    const online = todos.filter((d) => d.online).length;
    pintar(raizLista.querySelector("[data-parte=sub]"), todos.length
      ? `${todos.length} aparelhos conhecidos, ${online} na rede agora. Cada um é reconhecido pelo MAC, então o histórico continua mesmo se o IP mudar.`
      : "Nenhum aparelho encontrado ainda.");
  }

  function atualizarLista(estado) {
    if (!raizLista) return;
    pintarLista(estado);
    pintarBotaoVarrer(raizLista.querySelector("[data-acao=varrer]"), estado);
  }

  HN.visoes.aparelhos = {
    titulo: "Aparelhos",
    montar: montarLista,
    atualizar: atualizarLista,
    desmontar() { raizLista = null; },
  };
})(window.HN = window.HN || {});
