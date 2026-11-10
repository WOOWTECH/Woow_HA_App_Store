export const meta = {
  id: 'p39', title: 'Safe arithmetic expression calculator', category: 'Utilities', version: '1.1.0',
  description: 'Parse decimal arithmetic with parentheses, unary signs, remainder, and right-associative powers.',
  example: { expression: '(12.5 + 7.5) * 3 - 2^3^2 / 16' },
  fields: [{ key: 'expression', label: 'Arithmetic expression', type: 'text' }]
};
export function run(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('input must be an object');
  if (typeof input.expression !== 'string' || !input.expression.trim() || input.expression.length > 1000) throw new Error('expression must be a nonempty string of at most 1000 characters');
  const expression = input.expression.trim(), tokens = [];
  let offset = 0;
  while (offset < expression.length) {
    if (/\s/.test(expression[offset])) { offset++; continue; }
    const number = /^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?/.exec(expression.slice(offset));
    if (number) { tokens.push({ type: 'number', value: Number(number[0]), position: offset + 1 }); offset += number[0].length; }
    else if ('+-*/%^()'.includes(expression[offset])) { tokens.push({ type: expression[offset], position: offset + 1 }); offset++; }
    else throw new Error(`unsupported character at position ${offset + 1}`);
    if (tokens.length > 512) throw new Error('expression exceeds 512 tokens');
  }
  tokens.push({ type: 'end', position: expression.length + 1 });
  let cursor = 0, depth = 0;
  const checked = value => {
    if (!Number.isFinite(value) || Math.abs(value) > 1e100) throw new Error('number or intermediate result must be finite with magnitude at most 1e100');
    return value;
  };
  const take = type => {
    if (tokens[cursor].type !== type) return false;
    cursor++;
    return true;
  };
  function primary() {
    const token = tokens[cursor];
    if (take('number')) return checked(token.value);
    if (take('(')) {
      const value = sum();
      if (!take(')')) throw new Error(`expected closing parenthesis at position ${tokens[cursor].position}`);
      return value;
    }
    throw new Error(`expected a number or parenthesis at position ${token.position}`);
  }
  function power() {
    const base = primary();
    return take('^') ? checked(base ** unary()) : base;
  }
  function unary() {
    depth++;
    if (depth > 128) throw new Error('expression nesting exceeds 128 levels');
    let value;
    if (take('+')) value = unary();
    else if (take('-')) value = -unary();
    else value = power();
    depth--;
    return checked(value);
  }
  function product() {
    let value = unary();
    while (['*', '/', '%'].includes(tokens[cursor].type)) {
      const operator = tokens[cursor++].type, right = unary();
      if ((operator === '/' || operator === '%') && right === 0) throw new Error('division or remainder by zero is not allowed');
      value = checked(operator === '*' ? value * right : operator === '/' ? value / right : value % right);
    }
    return value;
  }
  function sum() {
    let value = product();
    while (['+', '-'].includes(tokens[cursor].type)) {
      const operator = tokens[cursor++].type, right = product();
      value = checked(operator === '+' ? value + right : value - right);
    }
    return value;
  }
  const value = sum();
  if (tokens[cursor].type !== 'end') throw new Error(`unexpected token at position ${tokens[cursor].position}; implicit multiplication is not supported`);
  const result = Number(value.toPrecision(12));
  return { expression, result: result === 0 ? 0 : result };
}
