import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {runInNewContext} from 'node:vm';

const source = await readFile(new URL('../src/content/policy-engine.js', import.meta.url), 'utf8');
const scope = {};
runInNewContext(source, {globalThis: scope});
const decide = (text, destination = 'not_approved') => scope.GovernancaPromptPolicy.evaluate(text, {destination});
const rules = result => result.findings.map(item => item.rule);

function cpf(base) {
  let digits = String(base).padStart(9, '0');
  for (let size = 9; size <= 10; size++) {
    const sum = [...digits].reduce((total, digit, index) => total + Number(digit) * (size + 1 - index), 0);
    digits += String((sum * 10) % 11 % 10);
  }
  return digits;
}
function cnpj(base) {
  let digits = String(base).padStart(12, '0');
  for (const weights of [[5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2],
    [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]]) {
    const sum = weights.reduce((total, weight, index) => total + Number(digits[index]) * weight, 0);
    digits += String(sum % 11 < 2 ? 0 : 11 - sum % 11);
  }
  return digits;
}

test('R01 bloqueia marcador PEM sem registrar seu conteúdo', () => {
  const result = decide('-----BEGIN PRIVATE KEY-----\nmaterial sintético');
  assert.equal(result.action, 'BLOCK');
  assert.ok(rules(result).includes('R01'));
  assert.doesNotMatch(JSON.stringify(result), /material sintético/);
  assert.equal(decide('-----BEGIN PRI\u200BVATE KEY-----').action, 'BLOCK');
});

test('R02 e R03 distinguem credencial plausível, candidato e placeholder', () => {
  assert.equal(decide('Como redefinir minha senha no portal?').action, 'ALLOW');
  assert.equal(decide('Minha senha é <SENHA>; explique como alterar').action, 'ALLOW');
  assert.equal(decide('senha=chaveSintetica987').action, 'BLOCK');
  assert.equal(decide('senha: "frase sintética longa"').action, 'REVIEW');
  assert.equal(decide('postgres://usuario:segredoSintetico987@host/base').action, 'BLOCK');
  assert.equal(decide('Authorization: Bearer tokenSintetico123456789').action, 'REVIEW');
});

test('R04 diferencia um e vários códigos de recuperação sintéticos', () => {
  assert.equal(decide('Códigos de recuperação: ABCD-1234').action, 'REVIEW');
  assert.equal(decide('Backup codes: ABCD-1234 EFGH-5678').action, 'BLOCK');
});

test('R05 bloqueia qualquer CPF válido no destino não aprovado sem guardar o número', () => {
  assert.equal(decide('CPF fictício: 000.000.000-00').action, 'ALLOW');
  const values = [1, 2, 3, 4, 5].map(value => cpf(900000000 + value));
  assert.equal(decide(values[0]).action, 'BLOCK');
  assert.equal(decide('CPF sintético: 900.000.001-75').action, 'BLOCK');
  assert.equal(decide('CPF sintético: 900.000.001-76').action, 'ALLOW');
  assert.equal(decide('CPF sintético: 900-000-001-75').action, 'BLOCK');
  assert.equal(decide(values.slice(0, 3).join('\n')).action, 'BLOCK');
  assert.equal(decide(`${values[0]}\n${values[0]}`).action, 'BLOCK');
  const blocked = decide(values.join('\n'));
  assert.equal(blocked.action, 'BLOCK');
  assert.equal(blocked.findings.find(item => item.rule === 'R05').count, 5);
  assert.doesNotMatch(JSON.stringify(blocked), /90000000175/);
  assert.equal(decide(values.join('\n'), 'client_data_approved').action, 'WARN');
});

test('R06 e R07 combinam CPF válido com estrutura ou categoria sensível', () => {
  const values = [1, 2].map(value => cpf(800000000 + value));
  const table = `Nome, CPF, salário\nPessoa A, ${values[0]}, 100\nPessoa B, ${values[1]}, 200`;
  const result = decide(table);
  assert.equal(result.action, 'BLOCK');
  assert.ok(rules(result).includes('R06'));
  const health = decide(`CPF ${values[0]} diagnóstico sintético`);
  assert.equal(health.action, 'BLOCK');
  assert.ok(rules(health).includes('R07'));
  assert.equal(decide('Como proteger dados de saúde?').action, 'ALLOW');
});

test('R08 exige conteúdo substancial; R09 não bloqueia assunto fiscal isolado', () => {
  assert.equal(decide('CONFIDENCIAL: crie um título para esta política').action, 'ALLOW');
  assert.equal(decide(`SIGILOSO\n${'texto fictício '.repeat(50)}`).action, 'REVIEW');
  assert.equal(decide('Como apurar DAS de uma empresa?').action, 'ALLOW');
  const companies = Array.from({length: 10}, (_, index) => cnpj(100000000001 + index));
  assert.equal(decide(`Faturamento\n${companies.join('\n')}`).action, 'REVIEW');
});
