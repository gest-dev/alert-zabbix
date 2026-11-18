# Validação — 16/11/2026 — versão 8

- Cliente validado em um servidor Zabbix **6.4.21**, com a conexão configurada
  apenas na conta local. O código e o pacote começam sem endereço ou usuário.
- Retorno real: a consulta bruta tinha **5 problemas não resolvidos**, todos
  pertencentes a hosts com monitoramento desativado. Após o filtro, o aplicativo
  retornou **zero problemas elegíveis**, sem modificar nenhum host do servidor.
- `trigger.get` usa `active: true` e consulta o status dos hosts. Problemas de
  triggers excluídas pela API, de hosts desativados e de triggers com algum host
  desativado ficam fora da lista usada pelo contador e pelas notificações.
- A chamada `problem.get` usa `recent: false`; eventos com `r_eventid` diferente
  de zero também são descartados. O teste inclui um evento resolvido para
  verificar sua exclusão da lista e da consulta dos hosts afetados.
- Credencial salva no chaveiro do Ubuntu; consulta completa repetida com leitura
  da credencial do chaveiro, sem senha no pacote ou na configuração JSON.
- Testes automatizados do cliente verificam requisições somente de consulta,
  associação dos hosts, ordenação e filtro por severidade, login recusado sem
  repetição, logout após falha de consulta, uso de token, ausência de credenciais
  na configuração, permissões do arquivo e recusa de redirecionamentos.
- Sintaxe de todos os arquivos Python validada pelo empacotamento.
- Quatorze testes do cliente passaram na versão 8, incluindo a remoção após desativar
  um host, triggers filtradas pela API, vários hosts na mesma trigger e a
  preservação do alerta de host habilitado que ficou indisponível.
- Na versão 8, 35 verificações da tela de configuração e 43 da extensão passaram.
  A conexão, a aba Barra e avisos e o menu de problemas foram inspecionados em
  capturas da sessão GNOME isolada.
- A posição alternou entre esquerda e direita a partir do arquivo salvo, mesmo
  sem servidor configurado. O botão e seu menu foram preservados durante a mudança,
  e a posição escolhida foi restaurada após desativar e reativar a extensão.
- A prévia acompanhou a posição; tema e posição foram salvos sem acessar a API
  ou o chaveiro. Salvar a conexão preservou a posição escolhida. Preferências
  visuais não sobrescreveram endereço ou usuário da conexão salva.
- O atalho Aparência e posição abriu a aba correta na janela já existente.
- Ícone original criado com image_gen, preservado em PNG RGBA com transparência.
  O ícone da barra é um SVG simbólico correspondente. Ambos estão no pacote.
- Os testes verificaram o ícone da janela no tema local, a renderização simbólica
  na barra, os tamanhos configurados e o uso da marca nas notificações nativas.
  A fonte de notificações do Zabbix foi liberada ao desativar a extensão.
- Capturas da janela, da barra e de uma notificação de teste foram inspecionadas.
- Controles de letra, ícone e espaço na barra, além da letra da janela, foram
  incluídos na aba Barra e avisos. Os valores são validados e salvos sem depender
  da conexão. Configurações anteriores recebem os tamanhos padrão ao carregar.
- Os testes da barra verificam os tamanhos mínimos e máximos, a largura real do
  ícone renderizado, a aplicação do espaçamento e a preservação dos tamanhos após
  receber dados, perder conexão ou desativar e reativar a extensão.
- No diagnóstico da sessão principal, o GNOME ainda executava a versão 4,
  enquanto a versão 6 estava instalada e a posição esquerda estava salva.
  O método público de recarga não era implementado; o código do GNOME 50 confirma
  que a substituição da versão carregada requer uma nova sessão.
- A tela passou a mostrar um aviso quando a versão em execução difere da
  instalada, e a mensagem de salvamento explica quando a posição será aplicada.
- A configuração inicial começa vazia e não acessa a rede ou o chaveiro antes
  de informar o servidor. Testar não grava dados; salvar valida a conexão;
  uma tentativa recusada preserva a configuração e a credencial anteriores.
- Varredura dos arquivos do projeto e do conteúdo descompactado do pacote
  confirmou ausência do endereço, usuário e senhas pessoais usados na validação.
- Backups antigos foram preservados nos dados locais da conta, fora do projeto.
- A conexão local já existente foi validada após retirar os dados do código.
- O teste gráfico verifica a lista diretamente no menu, a remoção de problemas
  resolvidos após atualizar, o estado vazio, a ocultação de dados anteriores em
  falha de conexão, a pausa em erro de autenticação, a recuperação, a janela de
  configuração e o ciclo de desativação e reativação.
- A barra mostra permanentemente o total e a maior gravidade. Os testes também
  verificam o resumo inicial dos problemas atuais, a notificação única de novos
  eventos, o aviso de aumento de gravidade, o silêncio em consultas sem mudanças,
  a opção de desligar os avisos e a ausência de alerta ao resolver os problemas.
- Captura do menu inspecionada em `/tmp/alert-zabbix-preview.png` com dados de teste.
- Pacote instalado na conta local e ativação salva. Se o GNOME ainda executar uma
  versão anterior, a atualização da barra será carregada após sair e entrar na
  sessão. A sessão principal não foi encerrada ou reiniciada.

As contagens refletem o momento da validação e podem mudar no servidor.

## VPN L2TP/IPsec — 18/11/2026

- A porta UDP de origem do xl2tpd no servidor Zabbix foi alterada para 17002,
  com o seletor IPsec local correspondente; o destino L2TP permaneceu na 1701.
- A intervenção na VM preservou as credenciais e a configuração do Ubuntu.
  Foram usados backup privado e reversão automática, cancelada após os testes.
- Sete amostras em aproximadamente dois minutos confirmaram a mesma sessão PPP,
  rotas dos dois hosts pela VPN e `agent.ping=1` no banco e no servidor web.
- O perfil passou a apresentar uma única sessão IPsec. Os serviços permaneceram
  habilitados para inicialização.
- O Ubuntu estava conectado por outro gateway na verificação final; a
  coexistência dos dois clientes no mesmo gateway não foi validada.

Procedimento, referências e limites: [VPN L2TP/IPsec](zabbix/VPN.md).
