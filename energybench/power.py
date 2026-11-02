"""Weather -> power: one ridge regression per country, fitted on ERA5.

Features are ws, ws^2 and ws^3 at every 1.5 deg cell around the country; the
regression learns where the fleet is and roughly how its power curve behaves.
It is deliberately simple and shared by all models, so differences in the
score come from the weather forecast, not from the conversion.
"""
import numpy as np

from .config import COUNTRIES, MARGIN


def country_cells(lat, lon, country):
    if country not in COUNTRIES:  # Europe: every cell
        return np.ones((len(lat), len(lon)), bool)
    la0, la1, lo0, lo1 = COUNTRIES[country][1]
    la = (lat >= la0 - MARGIN) & (lat <= la1 + MARGIN)
    lo = (lon >= lo0 - MARGIN) & (lon <= lo1 + MARGIN)
    return la[:, None] & lo[None, :]


def features(ws, cells):
    x = ws[:, cells]
    return np.concatenate([x, x ** 2, x ** 3], axis=1)


class RidgePower:
    def __init__(self, cells, alpha=1.0):
        self.cells, self.alpha = cells, alpha

    def fit(self, ws, y):
        x = features(ws, self.cells)
        self.mu, self.sd = x.mean(0), x.std(0) + 1e-6
        x = (x - self.mu) / self.sd
        self.b = y.mean()
        a = x.T @ x + self.alpha * len(x) * np.eye(x.shape[1])
        self.w = np.linalg.solve(a, x.T @ (y - self.b))
        return self

    def predict(self, ws):
        x = (features(ws, self.cells) - self.mu) / self.sd
        return np.clip(x @ self.w + self.b, 0.0, 1.1)


def fit_with_validation(ws_tr, y_tr, ws_va, y_va, cells, alphas=(1e-6, 1e-5, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2, 3e-2, 0.1, 0.3, 1.0)):
    """Pick the ridge strength on the validation year, refit on train + val."""
    maes = [np.mean(np.abs(RidgePower(cells, a).fit(ws_tr, y_tr).predict(ws_va) - y_va)) for a in alphas]
    best = alphas[int(np.argmin(maes))]
    model = RidgePower(cells, best).fit(np.concatenate([ws_tr, ws_va]), np.concatenate([y_tr, y_va]))
    return model, best, min(maes)
