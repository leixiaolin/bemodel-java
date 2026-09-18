from datetime import datetime
from sqlalchemy import select, func, inspect, DateTime, update
from .java_compat import snake_case
from .page_result import page_num, page_size, page_result


class BaseDAO:
    def __init__(self, session, model):
        self.session, self.model = session, model

    def finish(self):
        self.session.flush()
        if not self.session.info.get("transaction_depth"):
            self.session.commit()

    def entity(self, data):
        if isinstance(data, self.model):
            return data
        fields = inspect(self.model).attrs.keys()
        values = {snake_case(k): v for k, v in data.items() if snake_case(k) in fields}
        for column in inspect(self.model).columns:
            if isinstance(column.type, DateTime) and isinstance(values.get(column.key), str):
                values[column.key] = datetime.fromisoformat(values[column.key])
        return self.model(**values)

    def select_by_id(self, id):
        return self.session.get(self.model, id)

    def select_list(self, *conditions, order=(), limit=None):
        query = select(self.model).where(*conditions).order_by(*order)
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))

    def select_one(self, *conditions, order=()):
        return next(iter(self.select_list(*conditions, order=order, limit=1)), None)

    def select_count(self, *conditions):
        return self.session.scalar(select(func.count()).select_from(self.model).where(*conditions))

    def insert(self, data):
        entity = self.entity(data)
        # MyBatis returns the input bean with generated id, without reloading DB defaults.
        supplied = {a.key: getattr(entity, a.key) for a in inspect(self.model).column_attrs}
        self.session.add(entity)
        self.finish()
        generated_id = entity.id
        self.session.expunge(entity)
        for name, value in supplied.items():
            setattr(entity, name, generated_id if name == "id" else value)
        return entity

    def update_by_id(self, data):
        entity = self.entity(data)
        if entity.id is None:
            return entity
        values = {a.key: getattr(entity, a.key) for a in inspect(self.model).column_attrs
                  if a.key != "id" and getattr(entity, a.key) is not None}
        # A loaded bean may already have been assigned None by its caller. Detach
        # before flushing so ORM dirty tracking cannot bypass MyBatis NOT_NULL.
        with self.session.no_autoflush:
            if inspect(entity).session is self.session:
                self.session.expunge(entity)
            if values:
                self.session.execute(update(self.model).where(self.model.id == entity.id)
                    .values(**values).execution_options(synchronize_session="fetch"))
            self.finish()
        return entity

    def delete_by_id(self, id):
        entity = self.select_by_id(id)
        if entity is not None:
            self.session.delete(entity)
            self.finish()

    def delete(self, *conditions):
        for entity in self.select_list(*conditions):
            self.session.delete(entity)
        self.finish()

    def page(self, *conditions, page=1, size=20, order=()):
        page, size = page_num(page), page_size(size)
        rows = list(self.session.scalars(select(self.model).where(*conditions)
            .order_by(*order).offset((page - 1) * size).limit(size)))
        return page_result(rows, self.select_count(*conditions), page, size)
