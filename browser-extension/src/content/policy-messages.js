(() => {
  const descriptions = Object.freeze({
    R01: () => 'Marcador de chave privada detectado. Remova a chave do prompt.',
    R02: () => 'Possível token ou credencial de conexão detectado. Remova o valor do prompt.',
    R03: () => 'Possível senha ou chave declarada no texto. Remova o valor do prompt.',
    R04: () => 'Código(s) de recuperação detectado(s). Remova-os do prompt.',
    R05: count => count === 1
      ? 'CPF válido detectado. Remova ou masque o número.'
      : `${count} CPFs válidos distintos detectados. Remova ou masque os números.`,
    R06: count => `Tabela com ${count} ${count === 1 ? 'registro identificável' : 'registros identificáveis'} detectada. Remova ou masque os dados.`,
    R07: () => 'CPF associado a possível dado pessoal sensível. Remova ou masque os dados.',
    R08: () => 'Conteúdo extenso marcado como sigiloso. Consulte a governança antes de enviar.',
    R09: count => `Lote com ${count} empresas e faturamento. Consulte a governança antes de enviar.`,
    LIMIT: () => 'Texto acima do limite de análise desta versão. Reduza o conteúdo.',
    ENGINE: () => 'Não foi possível analisar o texto. Tente novamente ou procure suporte.',
    MANUAL: () => 'O bloqueio manual de todos os envios está ligado no popup.',
    MACHINE: () => 'Esta instalação ainda não está atribuída a uma pessoa. Confira o cadastro da instalação.',
    SYNC: () => 'O estado do bloqueio ainda está sincronizando. Aguarde um instante e tente novamente.'
  });
  function primary(decision) {
    const findings = Array.isArray(decision.findings) ? decision.findings : [];
    if (findings.some(item => item.rule === 'SYNC')) return 'SYNC';
    if (findings.some(item => item.rule === 'MANUAL')) return 'MANUAL';
    if (findings.some(item => item.rule === 'MACHINE')) return 'MACHINE';
    return findings.find(item => item.action === decision.action)?.rule || 'NONE';
  }
  function describe(decision) {
    const rule = decision.primaryRule || primary(decision);
    const count = decision.findings?.find(item => item.rule === rule)?.count || 1;
    const detail = descriptions[rule]?.(count, decision.action) || 'Nenhuma regra específica foi identificada.';
    if (decision.action === 'BLOCK') return `Envio bloqueado: ${detail}`;
    if (decision.action === 'REVIEW') return `Envio retido para revisão: ${detail}`;
    if (decision.action === 'WARN') return `Aviso antes do envio: ${detail}`;
    return 'Envio permitido pela política.';
  }
  globalThis.GovernancaPolicyMessages = Object.freeze({primary, describe});
})();
