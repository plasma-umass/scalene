import math
import pickle
import numpy as np
from numpy import linalg as LA

np.random.seed(1)

class SVM:
    """SVC with subgradient descent training.

    Arguments:
        lambda1: regularization parameter for L1 regularization (default: 1)
        lambda2: regularization parameter for L2 regularization (default: 1)
        iterations: number of training iterations (default: 500)
    """
    def __init__(self, lambda1=1, lambda2=1):
        self.lambda1 = lambda1
        self.lambda2 = lambda2

    def fit(self, X, y, iterations=500, disp=-1):
        """Fit the model using the training data.

        Arguments:
            X (ndarray, shape = (n_samples, n_features)):
                Training input matrix where each row is a feature vector.
                The data in X are passed in without a bias column!
            y (ndarray, shape = (n_samples,)):
                Training target. Each entry is either -1 or 1.
        
        Notes: This function must set member variables such that a subsequent call
        to get_params or predict uses the learned parameters, overwriting 
        any parameter values previously set by calling set_params.
        
        """
        n_features = X.shape[1]
        
        x = np.random.rand(n_features + 1)
        minimizer = x
        fmin = self.objective(x, X, y)
        
        for t in range(iterations):
            if disp != -1 and t % disp == 0:
                print("At iteration", t, "f(minimizer) =", fmin)
            alpha = 0.002 / math.sqrt(t + 1)
            subgrad = self.subgradient(x, X, y)
            x -= alpha * subgrad
            objective = self.objective(x, X, y)
            if (objective < fmin):
                fmin = objective
                minimizer = x

        self.w = minimizer[:-1]
        self.b = minimizer[-1]


    def objective(self, wb, X, y):
        """Compute the objective function for the SVM.

        Arguments:
            wb (ndarray, shape = (n_features+1,)):
                concatenation of the weight vector with the bias wb=[w,b] 
            X (ndarray, shape = (n_samples, n_features)):
                Training input matrix where each row is a feature vector.
                The data in X are passed in without a bias column!
            y (ndarray, shape = (n_samples,)):
                Training target. Each entry is either -1 or 1.

        Returns:
            obj (float): value of the objective function evaluated on X and y.
        """
        n_samples = X.shape[0]

        w = wb[:-1]
        b = wb[-1]

        sum = 0
        for n in range(n_samples):
            sum += max(0, 1 - y[n] * (np.dot(X[n], w) + b))

        return sum + self.lambda1 * LA.norm(w, 1) + self.lambda2 * (LA.norm(w, 2) ** 2)


# Proposed optimization:
# This code has been optimized by replacing the for loops with vectorized operations. This reduces the time complexity from O(n^2) to O(n), resulting in a substantial speedup.
    def subgradient(self, wb, X, y):
        """Compute the subgradient of the objective function.
        Arguments:
            wb (ndarray, shape = (n_features+1,)):
                concatenation of the weight vector with the bias wb=[w,b]
            X (ndarray, shape = (n_samples, n_features)):
                Training input matrix where each row is a feature vector.
                The data in X are passed in without a bias column!
            y (ndarray, shape = (n_samples,)):
                Training target. Each entry is either -1 or 1.
        Returns:
            subgrad (ndarray, shape = (n_features+1,)):
                subgradient of the objective function with respect to
                the coefficients wb=[w,b] of the linear model 
        """
        n_samples = X.shape[0]
        n_features = X.shape[1]
        w = wb[:-1]
        b = wb[-1]
        # Vectorized operations to replace for loops
        subgrad = np.zeros(n_features + 1)
        subgrad[:-1] = np.sum(-y[:, None] * X * (y * (X.dot(w) + b) < 1)[:, None], axis=0)
        subgrad[:-1] += self.lambda1 * np.sign(w) + 2 * self.lambda2 * w
        subgrad[-1] = np.sum(-y * (y * (X.dot(w) + b) < 1))
        return subgrad

    def subgradient_orig(self, wb, X, y):
        """Compute the subgradient of the objective function.

        Arguments:
            wb (ndarray, shape = (n_features+1,)):
                concatenation of the weight vector with the bias wb=[w,b]
            X (ndarray, shape = (n_samples, n_features)):
                Training input matrix where each row is a feature vector.
                The data in X are passed in without a bias column!
            y (ndarray, shape = (n_samples,)):
                Training target. Each entry is either -1 or 1.

        Returns:
            subgrad (ndarray, shape = (n_features+1,)):
                subgradient of the objective function with respect to
                the coefficients wb=[w,b] of the linear model 
        """
        n_samples = X.shape[0]
        n_features = X.shape[1]

        w = wb[:-1]
        b = wb[-1]

        subgrad = np.zeros(n_features + 1)
        for i in range(n_features):
            for n in range(n_samples):
                subgrad[i] += (- y[n] * X[n][i]) if y[n] * (np.dot(X[n], w) + b) < 1 else 0
            subgrad[i] += self.lambda1 * (-1 if w[i] < 0 else 1) + 2 * self.lambda2 * w[i]

        for n in range(n_samples):
            subgrad[-1] += - y[n] if y[n] * (np.dot(X[n], w) + b) < 1 else 0

        return subgrad

    def get_params(self):
        return (self.w, self.b)


def main():
    with open('data/svm_data.pkl', 'rb') as f:
        train_X, train_y, test_X, test_y = pickle.load(f)

    model = SVM()
    model.fit(train_X, train_y, iterations=500, disp = 1)
    print(model.get_params())
    
if __name__ == '__main__':
    main()
