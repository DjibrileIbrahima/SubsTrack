import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'

export default function SpendingChart({ data = [] }) {
  if (!data.length) return null

  const formatted = data.map((d) => {
    const monthDate = new Date(`${d.month}-01`)
    return {
      ...d,
      total: Number(d.total || 0),
      label: monthDate.toLocaleString('default', { month: 'short' }),
      fullLabel: monthDate.toLocaleString('default', {
        month: 'short',
        year: 'numeric',
      }),
    }
  })

  return (
    <div className="chart-wrap">
      <h3 className="section-title">Monthly Spending</h3>

      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={formatted} barSize={28}>
          <XAxis
            dataKey="label"
            axisLine={false}
            tickLine={false}
            tick={{ fontSize: 12, fill: 'var(--text-muted)' }}
          />

          <YAxis
            axisLine={false}
            tickLine={false}
            width={44}
            tick={{ fontSize: 12, fill: 'var(--text-muted)' }}
            tickFormatter={(v) => `$${Math.round(v)}`}
          />

          <Tooltip
            formatter={(value) => [`$${Number(value || 0).toFixed(2)}`, 'Spend']}
            labelFormatter={(_, payload) => payload?.[0]?.payload?.fullLabel || ''}
            contentStyle={{
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              fontSize: '13px',
            }}
          />

          <Bar dataKey="total" radius={[4, 4, 0, 0]}>
            {formatted.map((entry, i) => (
              <Cell
                key={entry.month || i}
                fill={i === formatted.length - 1 ? 'var(--accent)' : 'var(--bar-muted)'}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}