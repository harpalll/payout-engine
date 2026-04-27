import { useState, useEffect, useCallback } from 'react';
import {
  fetchMerchants,
  fetchBalance,
  fetchBankAccounts,
  fetchPayouts,
  fetchLedger,
  createPayout,
} from './api';

function formatPaise(paise) {
  return `₹${(paise / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;
}

function StatusBadge({ status }) {
  const colors = {
    pending: 'bg-yellow-100 text-yellow-800',
    processing: 'bg-blue-100 text-blue-800',
    completed: 'bg-green-100 text-green-800',
    failed: 'bg-red-100 text-red-800',
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${colors[status] || 'bg-gray-100 text-gray-800'}`}>
      {status}
    </span>
  );
}

export default function App() {
  const [merchants, setMerchants] = useState([]);
  const [selectedMerchant, setSelectedMerchant] = useState(null);
  const [balance, setBalance] = useState(null);
  const [bankAccounts, setBankAccounts] = useState([]);
  const [payouts, setPayouts] = useState([]);
  const [ledger, setLedger] = useState([]);
  const [tab, setTab] = useState('payouts');

  // Payout form
  const [amount, setAmount] = useState('');
  const [selectedBank, setSelectedBank] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState('');
  const [formSuccess, setFormSuccess] = useState('');

  // Load merchants on mount
  useEffect(() => {
    fetchMerchants().then((data) => {
      const list = data.results || data;
      setMerchants(list);
      if (list.length > 0) setSelectedMerchant(list[0].id);
    });
  }, []);

  // Load merchant data when selected merchant changes
  const loadMerchantData = useCallback(() => {
    if (!selectedMerchant) return;
    fetchBalance(selectedMerchant).then(setBalance);
    fetchBankAccounts(selectedMerchant).then((data) => {
      const list = data.results || data;
      setBankAccounts(list);
      if (list.length > 0 && !selectedBank) setSelectedBank(list[0].id);
    });
    fetchPayouts(selectedMerchant).then((data) => setPayouts(data.results || data));
    fetchLedger(selectedMerchant).then((data) => setLedger(data.results || data));
  }, [selectedMerchant]);

  useEffect(() => {
    loadMerchantData();
  }, [loadMerchantData]);

  // Poll every 3s for payout status updates
  useEffect(() => {
    if (!selectedMerchant) return;
    const interval = setInterval(() => {
      fetchBalance(selectedMerchant).then(setBalance);
      fetchPayouts(selectedMerchant).then((data) => setPayouts(data.results || data));
      fetchLedger(selectedMerchant).then((data) => setLedger(data.results || data));
    }, 3000);
    return () => clearInterval(interval);
  }, [selectedMerchant]);

  async function handleSubmit(e) {
    e.preventDefault();
    setFormError('');
    setFormSuccess('');
    setSubmitting(true);

    const amountPaise = Math.round(parseFloat(amount) * 100);
    if (!amountPaise || amountPaise <= 0) {
      setFormError('Enter a valid amount');
      setSubmitting(false);
      return;
    }

    const idempotencyKey = crypto.randomUUID();
    const { data, ok } = await createPayout({
      merchantId: selectedMerchant,
      amountPaise,
      bankAccountId: selectedBank,
      idempotencyKey,
    });

    if (ok) {
      setFormSuccess(`Payout created: ${data.id}`);
      setAmount('');
      loadMerchantData();
    } else {
      setFormError(data.error || data.detail || JSON.stringify(data));
    }
    setSubmitting(false);
  }

  const currentMerchant = merchants.find((m) => m.id === selectedMerchant);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <h1 className="text-xl font-semibold text-gray-900">Payout Engine</h1>
          <select
            className="border border-gray-300 rounded-md px-3 py-1.5 text-sm bg-white"
            value={selectedMerchant || ''}
            onChange={(e) => {
              setSelectedMerchant(e.target.value);
              setSelectedBank('');
            }}
          >
            {merchants.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-6 space-y-6">
        {/* Balance Cards */}
        {balance && (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="bg-white rounded-lg border border-gray-200 p-5">
              <p className="text-sm text-gray-500">Available Balance</p>
              <p className="text-2xl font-semibold text-gray-900 mt-1">
                {formatPaise(balance.available_balance)}
              </p>
            </div>
            <div className="bg-white rounded-lg border border-gray-200 p-5">
              <p className="text-sm text-gray-500">Held Balance</p>
              <p className="text-2xl font-semibold text-yellow-600 mt-1">
                {formatPaise(balance.held_balance)}
              </p>
            </div>
            <div className="bg-white rounded-lg border border-gray-200 p-5">
              <p className="text-sm text-gray-500">Merchant</p>
              <p className="text-lg font-medium text-gray-900 mt-1">
                {currentMerchant?.name}
              </p>
              <p className="text-xs text-gray-400 mt-0.5 font-mono truncate">
                {selectedMerchant}
              </p>
            </div>
          </div>
        )}

        {/* Create Payout Form */}
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="text-base font-semibold text-gray-900 mb-3">Create Payout</h2>
          <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
            <div className="flex-1 min-w-[140px]">
              <label className="block text-xs text-gray-500 mb-1">Amount (INR)</label>
              <input
                type="number"
                step="0.01"
                min="0.01"
                placeholder="500.00"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm"
                required
              />
            </div>
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs text-gray-500 mb-1">Bank Account</label>
              <select
                value={selectedBank}
                onChange={(e) => setSelectedBank(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm bg-white"
                required
              >
                {bankAccounts.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.account_holder_name} - {b.ifsc}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-1.5 bg-gray-900 text-white text-sm rounded-md hover:bg-gray-800 disabled:opacity-50"
            >
              {submitting ? 'Submitting...' : 'Submit Payout'}
            </button>
          </form>
          {formError && <p className="text-red-600 text-sm mt-2">{formError}</p>}
          {formSuccess && <p className="text-green-600 text-sm mt-2">{formSuccess}</p>}
        </div>

        {/* Tabs */}
        <div className="border-b border-gray-200">
          <nav className="flex gap-6">
            {['payouts', 'ledger'].map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`pb-2 text-sm font-medium border-b-2 ${
                  tab === t
                    ? 'border-gray-900 text-gray-900'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                {t === 'payouts' ? 'Payouts' : 'Ledger'}
              </button>
            ))}
          </nav>
        </div>

        {/* Payouts Table */}
        {tab === 'payouts' && (
          <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left text-xs text-gray-500 uppercase tracking-wider">
                <tr>
                  <th className="px-4 py-3">ID</th>
                  <th className="px-4 py-3">Amount</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Attempts</th>
                  <th className="px-4 py-3">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {payouts.length === 0 ? (
                  <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">No payouts yet</td></tr>
                ) : (
                  payouts.map((p) => (
                    <tr key={p.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 font-mono text-xs truncate max-w-[160px]">{p.id}</td>
                      <td className="px-4 py-3 font-medium">{formatPaise(p.amount_paise)}</td>
                      <td className="px-4 py-3"><StatusBadge status={p.status} /></td>
                      <td className="px-4 py-3">{p.attempts}</td>
                      <td className="px-4 py-3 text-gray-500">{new Date(p.created_at).toLocaleString()}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Ledger Table */}
        {tab === 'ledger' && (
          <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left text-xs text-gray-500 uppercase tracking-wider">
                <tr>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Amount</th>
                  <th className="px-4 py-3">Description</th>
                  <th className="px-4 py-3">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {ledger.length === 0 ? (
                  <tr><td colSpan={4} className="px-4 py-8 text-center text-gray-400">No entries</td></tr>
                ) : (
                  ledger.map((e) => (
                    <tr key={e.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3">
                        <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                          e.entry_type === 'credit' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                        }`}>
                          {e.entry_type}
                        </span>
                      </td>
                      <td className={`px-4 py-3 font-medium ${e.amount_paise < 0 ? 'text-red-600' : 'text-green-600'}`}>
                        {e.amount_paise > 0 ? '+' : ''}{formatPaise(Math.abs(e.amount_paise))}
                      </td>
                      <td className="px-4 py-3 text-gray-700">{e.description}</td>
                      <td className="px-4 py-3 text-gray-500">{new Date(e.created_at).toLocaleString()}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}
