/* A2UI surface interpreter — folds a command stream into a component map + data
   model, then renders the schedule form. Replaces the bundle's namespace
   A2UISurface (which does not exist in this stack). */
import { useMemo, useState } from 'react'
import { Input, DatePicker, Select, Checkbox, Button } from 'antd'
import dayjs from 'dayjs'
import { Icon } from '../admin/icons'
import type { SurfaceCmd, A2UIComponent } from './agentData'

type DataModel = Record<string, unknown>

export function A2UISurface({
  messages,
  onAction,
}: {
  messages: SurfaceCmd[]
  onAction: (action: { name: string }, data: { form: Record<string, unknown> }) => void
}) {
  // Fold the command stream: components by id + root + initial data model.
  const { components, root, initialModel } = useMemo(() => {
    const comps: Record<string, A2UIComponent> = {}
    let rootId = 'root'
    const model: DataModel = {}
    for (const cmd of messages) {
      if (cmd.updateComponents) {
        rootId = cmd.updateComponents.root
        for (const c of cmd.updateComponents.components) comps[c.id] = c
      }
      if (cmd.updateDataModel) {
        for (const entry of cmd.updateDataModel.contents) {
          model[entry.path] = entry.value
        }
      }
    }
    return { components: comps, root: rootId, initialModel: model }
  }, [messages])

  const [model, setModel] = useState<DataModel>(initialModel)

  const setPath = (path: string, value: unknown) =>
    setModel((m) => ({ ...m, [path]: value }))

  // Flatten /form/* into { title, date, time, attendees, remind }.
  const collectForm = (): Record<string, unknown> => {
    const form: Record<string, unknown> = {}
    for (const key of Object.keys(model)) {
      if (key.startsWith('/form/')) form[key.slice('/form/'.length)] = model[key]
    }
    return form
  }

  const renderComponent = (id: string): React.ReactNode => {
    const c = components[id]
    if (!c) return null
    const path = c.value?.path

    switch (c.componentType) {
      case 'Card':
        return (
          <div
            key={id}
            style={{
              border: '1px solid var(--color-border-secondary)',
              borderRadius: 'var(--radius-lg)',
              padding: 16,
              background: 'var(--color-bg-container)',
            }}
          >
            {c.title ? (
              <div style={{ fontWeight: 600, color: 'var(--color-text-heading)', marginBottom: 12 }}>{c.title}</div>
            ) : null}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {(c.children || []).map((childId) => renderComponent(childId))}
            </div>
          </div>
        )

      case 'Text':
        return (
          <div
            key={id}
            style={{
              fontSize: c.variant === 'caption' ? 12 : 14,
              color: 'var(--color-text-tertiary)',
            }}
          >
            {c.text}
          </div>
        )

      case 'Field':
        return (
          <div key={id} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {c.label ? (
              <span style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>{c.label}</span>
            ) : null}
            {(c.children || []).map((childId) => renderComponent(childId))}
          </div>
        )

      case 'TextField':
        return (
          <Input
            key={id}
            placeholder={c.placeholder}
            value={path ? String(model[path] ?? '') : ''}
            onChange={(e) => path && setPath(path, e.target.value)}
          />
        )

      case 'DateField':
        return (
          <DatePicker
            key={id}
            style={{ width: '100%' }}
            value={path && model[path] ? dayjs(String(model[path])) : undefined}
            onChange={(d) => path && setPath(path, d?.format('YYYY-MM-DD'))}
          />
        )

      case 'Select':
        return (
          <Select
            key={id}
            style={{ width: '100%' }}
            options={c.options}
            value={path ? (model[path] as string | undefined) : undefined}
            onChange={(v) => path && setPath(path, v)}
          />
        )

      case 'Checkbox':
        return (
          <Checkbox
            key={id}
            checked={path ? !!model[path] : false}
            onChange={(e) => path && setPath(path, e.target.checked)}
          >
            {c.label}
          </Checkbox>
        )

      case 'Button':
        return (
          <Button
            key={id}
            type="primary"
            icon={c.icon ? <Icon name={c.icon} /> : undefined}
            onClick={() => c.action && onAction(c.action, { form: collectForm() })}
          >
            {c.label}
          </Button>
        )

      default:
        return null
    }
  }

  return <>{renderComponent(root)}</>
}
