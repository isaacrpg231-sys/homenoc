/* HomeNOC: ajustes. Alertas (Telegram, Discord, Healthchecks), monitoramento,
   acesso pelo celular, Zabbix e o próprio computador. Segredos chegam
   mascarados ("••••1234"); enviar o valor mascarado mantém o segredo salvo. */
"use strict";
(function (HN) {
  const { fmt } = HN;
  const { html, cru, pintar, icone, alternar, toast, ocupado, resultado, lerFormulario } = HN.ui;

  const SECOES = [
    ["alertas", "Alertas"], ["monitor", "Monitoramento"], ["celular", "Celular"], ["zabbix", "Zabbix"], ["sistema", "Este computador"],
  ];
  let raiz = null, cfg = null, ultimaUrlQr = null;

  const sec = (nome) => raiz && raiz.querySelector(`#ajuste-${nome}`);

  function campo({ nome, rotulo, valor, tipo = "text", dica, min, max, placeholder, lista, desativado }) {
    return html`<label class="campo">
      <span>${rotulo}</span>
      <input type="${tipo}" name="${nome}" value="${valor == null ? "" : valor}" ${min != null ? cru(`min="${min}"`) : ""} ${max != null ? cru(`max="${max}"`) : ""}
        placeholder="${placeholder || ""}" autocomplete="off" spellcheck="false" ${lista ? cru("data-lista") : ""} ${desativado ? cru("disabled") : ""}>
      ${dica ? html`<small>${dica}</small>` : ""}
    </label>`;
  }

  // ------------------------------------------------------------------ montagem
  async function montar(el, estado, sub) {
    raiz = el;
    el.classList.add("estreita");
    pintar(el, html`<div class="visao-cabeca"><div><h1>Ajustes</h1><p>Carregando…</p></div></div>`, true);
    try {
      cfg = await HN.api("GET", "/api/config");
    } catch (e) {
      if (raiz === el) pintar(el, html`<div class="visao-cabeca"><div><h1>Ajustes</h1></div></div>${HN.ui.vazio("Não consegui carregar os ajustes", e.message)}`, true);
      return;
    }
    if (raiz !== el) return;
    desenhar(estado || HN.S.estado);
    el.addEventListener("submit", aoEnviar);
    el.addEventListener("click", aoClicar);
    el.addEventListener("change", aoMudar);
    if (sub) focar(sub);
  }

  function desenhar(estado) {
    ultimaUrlQr = null;
    pintar(raiz, html`
      <div class="visao-cabeca">
        <div><h1>Ajustes</h1><p>Tudo fica salvo neste computador, no arquivo <code>dados/config.json</code>.</p></div>
      </div>
      <nav class="atalhos" aria-label="Seções dos ajustes">${SECOES.map(([id, nome]) => html`<a class="botao pequeno" href="#ajustes/${id}">${nome}</a>`)}</nav>
      ${secaoAlertas()}
      ${secaoMonitor()}
      ${secaoCelular(estado)}
      ${secaoZabbix()}
      ${secaoSistema(estado)}`, true);
    atualizar(estado);
  }

  function secaoAlertas() {
    const a = cfg.alertas;
    return html`<section class="bloco" id="ajuste-alertas" tabindex="-1">
      <div class="bloco-cabeca"><h2>Alertas</h2><span class="nota">avisam no celular quando algo cai e quando volta</span></div>
      <form class="bloco-corpo grade" data-form="alertas" novalidate>
        <p class="resumo-estado" data-parte="estado-alertas"></p>
        <div class="grade grade-2">
          <div class="grade">
            <h3 class="subtitulo">Telegram</h3>
            <ol class="passos">
              <li>No Telegram, abra o <b>@BotFather</b>, envie <code>/newbot</code> e escolha um nome.</li>
              <li>Cole abaixo o token que ele responder.</li>
              <li>Abra o seu bot novo e toque em <b>Começar</b>.</li>
              <li>Clique em <b>Descobrir meu chat_id</b>.</li>
            </ol>
            ${campo({ nome: "alertas.telegram.token", rotulo: "Token do bot", valor: a.telegram.token, placeholder: "123456789:AAH…" })}
            <div class="linha-campos com-botao">
              ${campo({ nome: "alertas.telegram.chat_id", rotulo: "chat_id", valor: a.telegram.chat_id, placeholder: "Ex.: 812345678" })}
              <button type="button" class="botao" data-acao="chat-id">Descobrir meu chat_id</button>
            </div>
            <div class="resultado" data-parte="resultado-chat" hidden></div>
          </div>
          <div class="grade">
            <h3 class="subtitulo">Discord</h3>
            <p class="dica">No seu servidor: configurações do canal, Integrações, Webhooks, Novo webhook e Copiar URL.</p>
            ${campo({ nome: "alertas.discord.webhook", rotulo: "URL do webhook", valor: a.discord.webhook, placeholder: "https://discord.com/api/webhooks/…" })}
            <h3 class="subtitulo">Healthchecks.io <span class="discreto">(opcional)</span></h3>
            <p class="dica">Avisa você se o próprio computador do HomeNOC desligar ou travar. Crie um check grátis em healthchecks.io e cole a URL de ping.</p>
            ${campo({ nome: "alertas.healthchecks.url", rotulo: "URL de ping", valor: a.healthchecks.url, placeholder: "https://hc-ping.com/…" })}
          </div>
        </div>
        <div class="grade grade-2">
          ${alternar({ nome: "internet.alertar", marcado: cfg.internet.alertar, titulo: "Avisar quando a internet cair", descricao: "Sem internet não dá para enviar: o aviso chega assim que ela volta, com o tempo que ficou fora." })}
          ${alternar({ nome: "descoberta.avisar_novos", marcado: cfg.descoberta.avisar_novos, titulo: "Avisar sobre aparelhos novos", descricao: "Uma mensagem quando um aparelho desconhecido entrar na rede." })}
        </div>
        <div class="form-acoes">
          <button type="submit" class="botao primario">Salvar alertas</button>
          <button type="button" class="botao" data-acao="testar-alertas">Enviar mensagem de teste</button>
        </div>
        <div class="resultado" data-parte="resultado-alertas" hidden></div>
      </form>
    </section>`;
  }

  function secaoMonitor() {
    const m = cfg.monitor, i = cfg.internet, d = cfg.descoberta, t = cfg.trafego;
    return html`<section class="bloco" id="ajuste-monitor" tabindex="-1">
      <div class="bloco-cabeca"><h2>Monitoramento</h2><span class="nota">o que é testado e com que frequência</span></div>
      <form class="bloco-corpo grade" data-form="monitor" novalidate>
        <h3 class="subtitulo">Internet</h3>
        <div class="linha-campos">
          ${campo({ nome: "internet.alvos", rotulo: "Servidores testados", valor: i.alvos.join(", "), lista: true, dica: "De 1 a 4, separados por vírgula. A internet só cai quando nenhum responde." })}
          ${campo({ nome: "internet.lenta_ms", rotulo: "Lenta acima de (ms)", valor: i.lenta_ms, tipo: "number", min: 20, max: 2000 })}
        </div>
        <h3 class="subtitulo">Testes</h3>
        <div class="linha-campos">
          ${campo({ nome: "monitor.intervalo_s", rotulo: "Testar a cada (segundos)", valor: m.intervalo_s, tipo: "number", min: 15, max: 3600 })}
          ${campo({ nome: "monitor.tentativas", rotulo: "Tentativas por teste", valor: m.tentativas, tipo: "number", min: 1, max: 5 })}
          ${campo({ nome: "monitor.timeout_ms", rotulo: "Espera por resposta (ms)", valor: m.timeout_ms, tipo: "number", min: 300, max: 5000 })}
          ${campo({ nome: "monitor.confirmacao_s", rotulo: "Confirmar queda após (segundos)", valor: m.confirmacao_s, tipo: "number", min: 0, max: 120, dica: "Testa de novo antes de avisar, para evitar alarme falso." })}
        </div>
        <h3 class="subtitulo">Descoberta e tráfego</h3>
        <div class="linha-campos">
          ${campo({ nome: "descoberta.intervalo_min", rotulo: "Varrer a rede a cada (minutos)", valor: d.intervalo_min, tipo: "number", min: 1, max: 1440 })}
          ${campo({ nome: "trafego.intervalo_s", rotulo: "Ler o tráfego a cada (segundos)", valor: t.intervalo_s, tipo: "number", min: 10, max: 600 })}
          ${campo({ nome: "retencao_dias", rotulo: "Guardar histórico por (dias)", valor: cfg.retencao_dias, tipo: "number", min: 1, max: 90 })}
        </div>
        <div class="grade grade-2">
          ${alternar({ nome: "descoberta.testar_portas", marcado: d.testar_portas, titulo: "Testar portas comuns", descricao: "Ajuda a reconhecer o tipo de cada aparelho. Só testa a sua rede, a cada 6 horas por aparelho." })}
          ${alternar({ nome: "trafego.ativo", marcado: t.ativo, titulo: "Medir o tráfego da internet", descricao: "Lê os contadores do roteador por UPnP." })}
        </div>
        <div class="form-acoes"><button type="submit" class="botao primario">Salvar monitoramento</button></div>
        <div class="resultado" data-parte="resultado-monitor" hidden></div>
      </form>
    </section>`;
  }

  function secaoCelular(estado) {
    const a = (estado && estado.acesso) || {};
    const local = a.local !== false;
    return html`<section class="bloco" id="ajuste-celular" tabindex="-1">
      <div class="bloco-cabeca"><h2>Acesso pelo celular</h2><span class="nota">pelo Wi-Fi de casa, nunca pela internet</span></div>
      <form class="bloco-corpo grade" data-form="acesso" novalidate>
        ${!local ? html`<p class="faixa"><span>Você está no celular. Estes ajustes só podem ser mudados no computador onde o HomeNOC está rodando.</span></p>` : ""}
        ${alternar({ nome: "rede_local", marcado: a.rede_local, titulo: "Permitir abrir o HomeNOC pelo celular", descricao: "Qualquer aparelho do seu Wi-Fi poderá abrir a página, mas só entra quem souber a senha.", desativado: !local })}
        <div class="linha-campos curta">
          ${campo({ nome: "senha", rotulo: a.senha_definida ? "Nova senha" : "Senha", tipo: "password", placeholder: a.senha_definida ? "Deixe em branco para manter a atual" : "Pelo menos 6 caracteres", desativado: !local })}
        </div>
        <div class="form-acoes"><button type="submit" class="botao primario" ${local ? "" : cru("disabled")}>Salvar acesso</button></div>
        <div class="resultado" data-parte="resultado-acesso" hidden></div>
        <div data-parte="qr"></div>
      </form>
    </section>`;
  }

  function secaoZabbix() {
    const z = cfg.zabbix;
    return html`<section class="bloco" id="ajuste-zabbix" tabindex="-1">
      <div class="bloco-cabeca"><h2>Zabbix</h2><span class="nota">opcional</span></div>
      <form class="bloco-corpo grade" data-form="zabbix" novalidate>
        <p class="dica">Se você usa o Zabbix (por exemplo, na máquina virtual do guia em <code>integracoes/zabbix</code>), o HomeNOC mostra quais aparelhos ele monitora e os problemas ativos. Use o token de um usuário <b>somente leitura</b>.</p>
        <p class="resumo-estado" data-parte="estado-zabbix"></p>
        <div class="linha-campos">
          ${campo({ nome: "zabbix.url", rotulo: "Endereço do Zabbix", valor: z.url, placeholder: "http://192.168.0.20/zabbix", dica: "O final /api_jsonrpc.php é completado sozinho." })}
          ${campo({ nome: "zabbix.token", rotulo: "Token da API", valor: z.token, placeholder: "Gerado em Usuários, API tokens" })}
        </div>
        <div class="form-acoes">
          <button type="submit" class="botao primario">Salvar Zabbix</button>
          <button type="button" class="botao" data-acao="testar-zabbix">Testar conexão</button>
        </div>
        <div class="resultado" data-parte="resultado-zabbix" hidden></div>
      </form>
    </section>`;
  }

  function secaoSistema(estado) {
    const e = estado || {};
    const auto = e.autostart || {};
    const local = !e.acesso || e.acesso.local !== false;
    return html`<section class="bloco" id="ajuste-sistema" tabindex="-1">
      <div class="bloco-cabeca"><h2>Este computador</h2></div>
      <div class="bloco-corpo grade">
        ${auto.suportado
          ? alternar({ nome: "autostart", marcado: auto.ativo, titulo: "Abrir o HomeNOC quando o Windows iniciar", descricao: "Ele roda em segundo plano, sem janela. A página abre pelo atalho ou em http://127.0.0.1:8765.", desativado: !local })
          : html`<p class="dica">Para iniciar junto com o sistema no Linux, use o serviço do systemd descrito no README.</p>`}
        <dl class="ficha">
          <dt>Versão</dt><dd>HomeNOC ${e.versao || ""}</dd>
          <dt>Endereço</dt><dd class="end">http://127.0.0.1:8765</dd>
          ${e.pasta_dados ? html`<dt>Pasta dos dados</dt><dd><code>${e.pasta_dados}</code></dd>` : ""}
          ${e.iniciado_em ? html`<dt>Aberto desde</dt><dd>${fmt.dataHora(e.iniciado_em)}</dd>` : ""}
        </dl>
        <div class="form-acoes">
          <button type="button" class="botao" data-acao="csv">${icone("baixar")}Exportar aparelhos (CSV)</button>
          ${local ? html`<button type="button" class="botao perigo" data-acao="encerrar">Encerrar o HomeNOC</button>` : ""}
        </div>
      </div>
    </section>`;
  }

  // ------------------------------------------------------------------ estado ao vivo
  function estadoAlertas(estado) {
    const a = estado.alertas || {};
    const partes = [];
    if (!(a.canais || []).length) partes.push("Nenhum canal configurado ainda.");
    else partes.push(`Enviando para ${a.canais.join(" e ")}.`);
    if (a.ultimo_envio) partes.push(`Último alerta enviado ${fmt.ha(a.ultimo_envio, estado.agora)}.`);
    if (a.fila) partes.push(`${a.fila} ${a.fila === 1 ? "alerta esperando" : "alertas esperando"} a internet voltar.`);
    if (a.ultimo_erro) partes.push(`Última falha: ${a.ultimo_erro}`);
    if (a.healthchecks_configurado) {
      const h = a.healthchecks;
      partes.push(!h ? "Healthchecks configurado." : h.ok ? `Healthchecks recebeu o último sinal ${fmt.ha(h.em, estado.agora)}.` : `Healthchecks com falha: ${h.erro}`);
    }
    const ok = (a.canais || []).length && !a.ultimo_erro;
    return html`<span class="estado" data-estado="${ok ? "ok" : (a.canais || []).length ? "alerta" : "off"}">${partes.join(" ")}</span>`;
  }

  function estadoZabbix(estado) {
    const z = estado.zabbix || {};
    if (!z.configurado) return html`<span class="estado" data-estado="off">Não configurado.</span>`;
    if (z.ok === false) return html`<span class="estado" data-estado="critico">Sem conexão: ${z.erro}</span>`;
    if (!z.ok) return html`<span class="estado" data-estado="off">Conectando…</span>`;
    const n = (z.problemas || []).length;
    return html`<span class="estado" data-estado="${n ? "alerta" : "ok"}">Conectado ao Zabbix ${z.versao}: ${z.hosts} hosts, ${n ? `${n} ${n === 1 ? "problema ativo" : "problemas ativos"}` : "nenhum problema ativo"}.</span>`;
  }

  function qrSvg(url) {
    const q = window.qrcode(0, "M");
    q.addData(url);
    q.make();
    return q.createSvgTag({ cellSize: 4, margin: 0, scalable: true, title: "QR code com o endereço do HomeNOC" });
  }

  function pintarQr(estado) {
    const caixa = raiz.querySelector("[data-parte=qr]");
    const a = estado.acesso || {};
    const url = a.rede_local && (a.urls || [])[0];
    if (url === ultimaUrlQr) return;
    ultimaUrlQr = url;
    if (!a.rede_local) { pintar(caixa, ""); return; }
    if (!url) { pintar(caixa, html`<p class="dica">Ligado. O endereço aparece aqui assim que o HomeNOC descobrir o IP deste computador.</p>`); return; }
    pintar(caixa, html`<div class="qr">
      <div class="codigo">${cru(qrSvg(url))}</div>
      <div class="grade">
        <span>Aponte a câmera do celular para o código ou digite:</span>
        <span class="url-celular">${url}</span>
        <small class="dica">O celular precisa estar no mesmo Wi-Fi. Se não abrir, permita o Python no Firewall do Windows (redes privadas) quando ele perguntar.</small>
      </div>
    </div>`);
  }

  function atualizar(estado) {
    if (!raiz || !cfg || !estado) return;
    pintar(raiz.querySelector("[data-parte=estado-alertas]"), estadoAlertas(estado));
    pintar(raiz.querySelector("[data-parte=estado-zabbix]"), estadoZabbix(estado));
    pintarQr(estado);
    const auto = raiz.querySelector("input[name=autostart]");
    if (auto && !auto.dataset.enviando && estado.autostart) auto.checked = Boolean(estado.autostart.ativo);
  }

  function focar(sub) {
    const alvo = sec(sub);
    if (!alvo) return;
    alvo.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    alvo.focus({ preventScroll: true });
  }

  // ------------------------------------------------------------------ ações
  async function aoEnviar(ev) {
    const form = ev.target.closest("form[data-form]");
    if (!form) return;
    ev.preventDefault();
    const tipo = form.dataset.form;
    const botao = form.querySelector("button[type=submit]");
    const saida = form.querySelector(`[data-parte=resultado-${tipo}]`);
    const dados = lerFormulario(form);
    try {
      if (tipo === "acesso") {
        const r = await ocupado(botao, "Salvando…", () => HN.api("POST", "/api/acesso", { rede_local: dados.rede_local, senha: dados.senha || undefined }));
        form.querySelector("input[name=senha]").value = "";
        resultado(saida, true, r.rede_local ? "Acesso pelo celular ligado." : "Acesso pelo celular desligado: o HomeNOC só abre neste computador.");
        HN.app.atualizarJa();
        return;
      }
      cfg = await ocupado(botao, "Salvando…", () => HN.api("POST", "/api/config", dados));
      const nomes = { alertas: "Alertas salvos.", monitor: "Monitoramento salvo.", zabbix: "Zabbix salvo." };
      resultado(saida, true, nomes[tipo] || "Salvo.");
      if (tipo === "alertas") {
        form.querySelector("[name='alertas.telegram.token']").value = cfg.alertas.telegram.token;
        form.querySelector("[name='alertas.discord.webhook']").value = cfg.alertas.discord.webhook;
        form.querySelector("[name='alertas.healthchecks.url']").value = cfg.alertas.healthchecks.url;
      }
      if (tipo === "zabbix") {
        form.querySelector("[name='zabbix.url']").value = cfg.zabbix.url;
        form.querySelector("[name='zabbix.token']").value = cfg.zabbix.token;
      }
      toast(nomes[tipo] || "Salvo.");
      HN.app.atualizarJa();
    } catch (e) {
      resultado(saida, false, e.message);
    }
  }

  let encerrarArmado = null;
  async function aoClicar(ev) {
    const b = ev.target.closest("[data-acao]");
    if (!b) return;
    const acao = b.dataset.acao;
    const form = b.closest("form");
    if (acao === "chat-id") {
      const saida = form.querySelector("[data-parte=resultado-chat]");
      try {
        const r = await ocupado(b, "Procurando…", () => HN.api("POST", "/api/alertas/chat-id", { token: form.querySelector("[name='alertas.telegram.token']").value }));
        if (!r.ok) return resultado(saida, false, html`${r.erro} ${r.dica || ""}`);
        if (r.chats.length === 1) {
          form.querySelector("[name='alertas.telegram.chat_id']").value = r.chats[0].id;
          resultado(saida, true, html`Encontrei a conversa com <b>${r.chats[0].nome || "você"}</b>. Agora clique em <b>Salvar alertas</b>.`);
        } else {
          resultado(saida, true, html`Encontrei ${r.chats.length} conversas. Qual é a sua?
            <div class="form-acoes">${r.chats.map((c) => html`<button type="button" class="botao pequeno" data-acao="escolher-chat" data-chat="${c.id}">${c.nome || c.id}</button>`)}</div>`);
        }
      } catch (e) { resultado(saida, false, e.message); }
    } else if (acao === "escolher-chat") {
      form.querySelector("[name='alertas.telegram.chat_id']").value = b.dataset.chat;
      resultado(form.querySelector("[data-parte=resultado-chat]"), true, html`Escolhido. Agora clique em <b>Salvar alertas</b>.`);
    } else if (acao === "testar-alertas") {
      const saida = form.querySelector("[data-parte=resultado-alertas]");
      try {
        const r = await ocupado(b, "Enviando…", () => HN.api("POST", "/api/alertas/teste", lerFormulario(form).alertas));
        const tudoOk = r.resultados.every((x) => x.ok);
        resultado(saida, tudoOk, html`<ul>${r.resultados.map((x) => html`<li><b>${x.canal}:</b> ${x.mensagem}${x.dica ? html` <span class="discreto">${x.dica}</span>` : ""}</li>`)}</ul>`);
      } catch (e) { resultado(saida, false, e.message); }
    } else if (acao === "testar-zabbix") {
      const saida = form.querySelector("[data-parte=resultado-zabbix]");
      const z = lerFormulario(form).zabbix;
      try {
        const r = await ocupado(b, "Testando…", () => HN.api("POST", "/api/zabbix/teste", z));
        resultado(saida, r.ok, r.ok ? `Funcionou: Zabbix ${r.versao}, ${r.hosts} hosts, ${r.problemas} ${r.problemas === 1 ? "problema ativo" : "problemas ativos"}. Clique em Salvar Zabbix para usar.` : `Não funcionou: ${r.erro}`);
      } catch (e) { resultado(saida, false, e.message); }
    } else if (acao === "csv") {
      HN.ui.exportarCsv();
    } else if (acao === "encerrar") {
      if (!encerrarArmado) {
        b.textContent = "Clique de novo para encerrar";
        encerrarArmado = setTimeout(() => { encerrarArmado = null; if (b.isConnected) b.textContent = "Encerrar o HomeNOC"; }, 5000);
        return;
      }
      clearTimeout(encerrarArmado);
      encerrarArmado = null;
      try {
        await ocupado(b, "Encerrando…", () => HN.api("POST", "/api/encerrar"));
        HN.app.encerrado();
      } catch (e) { toast(e.message, 5000); b.textContent = "Encerrar o HomeNOC"; }
    }
  }

  async function aoMudar(ev) {
    const caixa = ev.target.closest("input[name=autostart]");
    if (!caixa) return;
    caixa.dataset.enviando = "1";
    try {
      const r = await HN.api("POST", "/api/autostart", { ativo: caixa.checked });
      caixa.checked = Boolean(r.ativo);
      toast(r.mensagem || (r.ativo ? "O HomeNOC vai abrir junto com o Windows." : "Não vai mais abrir junto com o Windows."), 4500);
    } catch (e) {
      caixa.checked = !caixa.checked;
      toast(e.message, 5000);
    } finally { delete caixa.dataset.enviando; }
  }

  HN.visoes.ajustes = {
    titulo: "Ajustes",
    montar, atualizar, focar,
    desmontar() { raiz = null; cfg = null; clearTimeout(encerrarArmado); encerrarArmado = null; },
  };
})(window.HN = window.HN || {});
