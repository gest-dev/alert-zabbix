# VPN L2TP/IPsec do servidor Zabbix

Registro da correção operacional aplicada em **18/11/2026** no cliente VPN do
servidor Zabbix. A intervenção ocorreu na VM; este documento preserva o
procedimento e a evidência de validação no repositório.

O aplicativo da barra continua consultando a API em modo de leitura. Seus
instaladores não configuram a VPN nem executam os comandos administrativos abaixo.

## Sintoma e diagnóstico

- O IPsec aparecia como estabelecido, mas a sessão L2TP/PPP caía ou não conectava.
- Os logs do PPP registravam autenticação aceita e, depois, desconexão; o L2TP
  registrava timeouts e tentativas automáticas de reconexão.
- Sem `ppp0`, as rotas dos hosts de produção voltavam para o gateway comum,
  e os agentes deixavam de responder na porta TCP 10050.
- Dois clientes apareciam no MikroTik com usuários e endereços VPN distintos,
  mas com o mesmo IP público de origem. Havia sessões IPsec sobrepostas do Zabbix
  e uma política estabelecida com portas UDP `1701 → 1701` para esse IP público.

Esse conjunto de evidências levantou a hipótese de disputa pelo tráfego de
retorno entre clientes atrás do mesmo NAT. A documentação do NetworkManager-l2tp
descreve a dificuldade de diferenciar esses clientes quando todos usam a porta
de origem 1701 e apresenta uma porta de origem alternativa como solução.
[Referência do cliente L2TP](https://github.com/nm-l2tp/NetworkManager-l2tp/blob/main/README.md#unable-to-establish-l2tp-connection-with-udp-source-port-1701).

Sessões IPsec estabelecidas, isoladamente, não comprovam que o PPP e as consultas
dos agentes estejam funcionando. A contagem dessas sessões também não equivale
à quantidade de usuários conectados.

## Alteração aplicada na VM

Foi escolhida uma porta UDP de origem própria para o Zabbix, disponível no
momento da intervenção:

| Componente | Antes | Depois |
| :--- | :--- | :--- |
| Origem L2TP no Zabbix | UDP 1701 | UDP 17002 |
| Destino L2TP no MikroTik | UDP 1701 | UDP 1701 |
| Consulta dos agentes | TCP 10050 | TCP 10050 |

Em `/etc/xl2tpd/xl2tpd.conf`, na seção existente `[global]`:

```ini
[global]
port = 17002
```

No perfil existente `/etc/ipsec.d/gest-zabbix.conf`:

```ini
leftprotoport=17/17002
rightprotoport=17/1701
```

O número `17` representa UDP. A porta de origem do xl2tpd e o seletor local do
IPsec precisam corresponder. Esses trechos mostram somente os campos relevantes;
devem ser ajustados no arquivo existente, preservando os demais parâmetros.

Foram preservados o login, a senha, a PSK, o endereço do servidor VPN e as rotas
por host. Credenciais, endereços pessoais e arquivos completos de autenticação
não fazem parte deste registro. A configuração da VPN do Ubuntu não foi alterada.

## Aplicação e recuperação

A intervenção administrativa exige acesso à VM e reinicia sua conexão VPN.
Antes de aplicar uma configuração equivalente em outro ambiente, confira a
disponibilidade da porta e preserve cópias privadas dos dois arquivos.

Na intervenção registrada:

1. As configurações anteriores foram copiadas para
   `/root/gest-vpn-backups/20261118T153034Z`, em diretório privado.
2. Foi preparado um temporizador de reversão automática de cinco minutos.
3. O xl2tpd foi parado, os dois campos de porta foram atualizados e o
   strongSwan foi reiniciado; depois, o xl2tpd foi iniciado novamente.
4. O perfil manteve `auto=start`. Não foi acrescentado um `ipsec up` manual em
   paralelo à inicialização automática.
5. A reversão automática foi cancelada após a validação. O backup foi preservado
   na VM, fora do repositório.

A sequência de serviços usada, após preparar o backup e atualizar os arquivos, foi:

```bash
sudo systemctl stop xl2tpd
sudo systemctl restart strongswan-starter
sudo systemctl start xl2tpd
```

O nome do serviço IPsec depende da distribuição; `strongswan-starter` corresponde
à instalação validada. A sequência, sozinha, não cria backup nem arma a reversão.

No MikroTik, a política gerada precisa aceitar as portas propostas pelo cliente.
A documentação descreve esse comportamento em `generate-policy=port-strict`.
[Referência de políticas IPsec](https://help.mikrotik.com/docs/spaces/ROS/pages/11993097/IPsec).

## Validação realizada

Após a alteração, foi observado:

- Uma única sessão IPsec do perfil do Zabbix e xl2tpd escutando na porta 17002.
- Interface `ppp0` presente e rotas dos dois hosts usando essa interface.
- Os agentes do banco e do servidor web retornando **`agent.ping=1`** pela VPN.
- Sete amostras ao longo de aproximadamente dois minutos, mantendo o mesmo
  processo PPP, as rotas corretas e as duas respostas positivas.
- Serviços VPN habilitados para inicialização e backup mantido após cancelar
  o temporizador de reversão.

Para uma nova conferência, consulte o estado do túnel e as rotas reais dos hosts:

```bash
sudo ipsec status
ip -brief address show dev ppp0
ip route get 198.51.100.20
```

`198.51.100.20` é um endereço de documentação: substitua pelo host monitorado.
Se `zabbix_get` estiver instalado no servidor ou proxy, consulte também o agente:

```bash
zabbix_get -s 198.51.100.20 -p 10050 -k agent.ping
```

O resultado esperado é `1`. A consulta deve sair pela VPN; uma conexão TCP
positiva sem resposta do agente não substitui esse teste.

### Limite da evidência

Durante a validação final, a VPN do Ubuntu estava ativa por **outro gateway**.
Portanto, os testes confirmaram a recuperação do Zabbix e o acesso aos dois
agentes, mas **ainda não validaram os dois clientes simultaneamente no mesmo
gateway VPN**. Essa confirmação exige uma nova observação nesse cenário e não
foi presumida a partir dos testes anteriores.
