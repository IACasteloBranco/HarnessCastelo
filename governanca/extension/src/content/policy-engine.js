(() => {
  const VERSION = '0.1.2';
  const MAX_CHARS = 100000;
  const PRIORITY = {ALLOW: 0, WARN: 1, REVIEW: 2, BLOCK: 3};
  const CPF_CANDIDATE = /(?<!\d)(?:\d{3}[.\s-]?\d{3}[.\s-]?\d{3}[-.\s]?\d{2}|\d{11})(?!\d)/g;
  const CNPJ_CANDIDATE = /(?<!\d)\d{2}[.\s-]?\d{3}[.\s-]?\d{3}[\/\s-]?\d{4}[-.\s]?\d{2}(?!\d)/g;
  const SENSITIVE = /\b(?:sa[uú]de|diagn[oó]stico|doen[cç]a|biometria|religi[aã]o|ra[cç]a|[eé]tnic[ao]|vida sexual|opini[aã]o pol[ií]tica|sindicat[oo]|filia[cç][aã]o sindical)\b/i;
  const FINANCIAL = /\b(?:sal[aá]rio|remunera[cç][aã]o|conta banc[aá]ria|banco|chave pix|pix|faturamento)\b/i;
  const PLACEHOLDER = /^(?:\*+|x+|0+|<[^>]+>|\[[^\]]+\]|exemplo|example|teste|test|placeholder|sua[-_ ]?chave[-_ ]?aqui|sua[-_ ]?senha)$/i;

  function normalize(text) {
    return String(text || '').normalize('NFKC')
      .replace(/[\u200B-\u200D\u2060\uFEFF]/g, '')
      .replace(/\r\n?/g, '\n');
  }
  function validCpf(digits) {
    if (!/^\d{11}$/.test(digits) || /^(\d)\1{10}$/.test(digits)) return false;
    for (let size = 9; size <= 10; size++) {
      const sum = [...digits.slice(0, size)].reduce((total, digit, index) =>
        total + Number(digit) * (size + 1 - index), 0);
      const check = (sum * 10) % 11 % 10;
      if (check !== Number(digits[size])) return false;
    }
    return true;
  }
  function validCnpj(digits) {
    if (!/^\d{14}$/.test(digits) || /^(\d)\1{13}$/.test(digits)) return false;
    const weights = [[5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2],
      [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]];
    for (let index = 0; index < 2; index++) {
      const sum = weights[index].reduce((total, weight, position) =>
        total + Number(digits[position]) * weight, 0);
      if ((sum % 11 < 2 ? 0 : 11 - sum % 11) !== Number(digits[12 + index])) return false;
    }
    return true;
  }
  function distinctMatches(text, pattern, validator, limit = 100) {
    const values = new Set();
    pattern.lastIndex = 0;
    for (const match of text.matchAll(pattern)) {
      const digits = match[0].replace(/\D/g, '');
      if (validator(digits)) values.add(digits);
      if (values.size >= limit) break;
    }
    return values;
  }
  function evaluate(original, context = {}) {
    const text = normalize(original);
    const destination = ['not_approved', 'masked_only', 'client_data_approved'].includes(context.destination)
      ? context.destination : 'not_approved';
    const findings = [];
    const add = (rule, action, count = 1) => findings.push({rule, action, count});
    if (text.length > MAX_CHARS) {
      add('LIMIT', 'REVIEW');
      return {version: VERSION, destination, action: 'REVIEW', findings};
    }

    // R01: marcador suficiente mesmo sem o restante do material PEM.
    if (/-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/i.test(text)) add('R01', 'BLOCK');

    // R02: formatos de fornecedores exigem catálogo externo; aqui há apenas
    // credenciais em URL e um Bearer de formato plausível, sem logar o valor.
    const credentialUrl = /\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|https?):\/\/[^\s/@:]+:([^\s/@]+)@/gi;
    for (const match of text.matchAll(credentialUrl)) {
      if (!PLACEHOLDER.test(match[1])) { add('R02', 'BLOCK'); break; }
    }
    if (/\bauthorization\s*:\s*bearer\s+[a-z0-9._~+\/-]{16,}/i.test(text)) add('R02', 'REVIEW');

    // R03: rótulo com atribuição, valor plausível e exclusão de placeholders.
    const assignment = /\b(?:senha|password|passwd|api[_ -]?key|client[_ -]?secret|access[_ -]?token)\b\s*(?::|=|é)\s*(?:"([^"\n]{1,128})"|'([^'\n]{1,128})'|([^\s"',;]{1,128}))/gi;
    for (const match of text.matchAll(assignment)) {
      const value = (match[1] || match[2] || match[3] || '').trim();
      if (!value || PLACEHOLDER.test(value) || /^(?:https?:\/\/|www\.)/i.test(value)) continue;
      if (value.length >= 8) { add('R03', /\s/.test(value) ? 'REVIEW' : 'BLOCK'); break; }
    }

    // R04: códigos só têm significado quando acompanhados do rótulo explícito.
    if (/(?:c[oó]digos? de recupera[cç][aã]o|backup codes|recovery codes)/i.test(text)) {
      const section = text.split(/(?:c[oó]digos? de recupera[cç][aã]o|backup codes|recovery codes)/i).slice(1).join(' ').slice(0, 1000);
      const codes = [...section.matchAll(/\b(?=[A-Z0-9-]{8,20}\b)(?=[A-Z0-9-]*\d)[A-Z0-9]{4,10}(?:-[A-Z0-9]{4,10})?\b/gi)]
        .map(match => match[0].toUpperCase());
      const distinct = new Set(codes);
      if (distinct.size >= 2) add('R04', 'BLOCK', distinct.size);
      else if (distinct.size === 1) add('R04', 'REVIEW');
    }

    const cpfs = distinctMatches(text, CPF_CANDIDATE, validCpf);
    const restrictedDestination = destination !== 'client_data_approved';
    if (cpfs.size && restrictedDestination) add('R05', 'BLOCK', cpfs.size);
    else if (cpfs.size) add('R05', 'WARN', cpfs.size);

    // R06: contar linhas com CPF válido, não ocorrências de palavras.
    const lines = text.split('\n').slice(0, 2000);
    const header = lines.findIndex(line => /\bnome\b/i.test(line) && /\bcpf\b/i.test(line));
    if (header >= 0) {
      const rows = lines.slice(header + 1).filter(line =>
        distinctMatches(line, CPF_CANDIDATE, validCpf, 2).size > 0);
      if (rows.length >= 5) add('R06', restrictedDestination ? 'BLOCK' : 'WARN', rows.length);
      else if (rows.length >= 2) add('R06', FINANCIAL.test(lines[header]) && restrictedDestination ? 'BLOCK' : 'REVIEW', rows.length);
    }

    // R07: exigir identificador válido próximo de uma categoria sensível.
    const sensitiveRows = lines.filter(line =>
      SENSITIVE.test(line) && distinctMatches(line, CPF_CANDIDATE, validCpf, 2).size > 0);
    if (sensitiveRows.length) add('R07', restrictedDestination ? 'BLOCK' : 'REVIEW', sensitiveRows.length);

    // R08: o marcador isolado não constitui um documento sigiloso.
    if (/\b(?:CONFIDENCIAL|SIGILOSO|USO INTERNO|N[AÃ]O DISTRIBUIR)\b/i.test(text) &&
        (text.length >= 500 || lines.length >= 8)) add('R08', 'REVIEW');

    // R09: assunto fiscal isolado é permitido; lote com faturamento vai à revisão.
    const cnpjs = distinctMatches(text, CNPJ_CANDIDATE, validCnpj);
    if (cnpjs.size >= 10 && /\bfaturamento\b/i.test(text) && restrictedDestination)
      add('R09', 'REVIEW', cnpjs.size);

    const action = findings.reduce((current, item) =>
      PRIORITY[item.action] > PRIORITY[current] ? item.action : current, 'ALLOW');
    return {version: VERSION, destination, action, findings};
  }
  globalThis.GovernancaPromptPolicy = Object.freeze({version: VERSION, evaluate});
})();
