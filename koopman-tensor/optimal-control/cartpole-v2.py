#%% Imports
import gym
import numpy as np

# from sklearn.kernel_approximation import RBFSampler

import sys
sys.path.append('../')
from tensor import KoopmanTensor
sys.path.append('../../')
import algorithmsv2_parallel as algorithmsv2
import observables
import utilities

#%% Load environment
env = gym.make('CartPole-v0')

#%% Define Q and R
# Q = np.eye(4)
# R = 0.0001

Q = np.array([
    [10, 0,  0, 0],
    [ 0, 1,  0, 0],
    [ 0, 0, 10, 0],
    [ 0, 0,  0, 1]
])
R = 0.1 #! force_mag (?)

#%% Construct datasets
seed = 123
env.seed(seed)
np.random.seed(seed)

num_datapoints = 50000

X = np.zeros([
    env.observation_space.sample().shape[0],
    num_datapoints
])
Y = np.zeros([
    env.observation_space.sample().shape[0],
    num_datapoints
])
U = np.zeros([
    1,
    num_datapoints
])

total_datapoints = 0
while total_datapoints < num_datapoints:
    x = env.reset()
    done = False
    while not done and total_datapoints < num_datapoints:
        X[:, total_datapoints] = x
        u = env.action_space.sample() # Sampled from random agent
        U[:, total_datapoints] = u
        y,reward,done,info = env.step(u)
        Y[:, total_datapoints] = y
        x = y
        total_datapoints += 1

#%% Tensor
# rbf_state_feature = RBFSampler(gamma=1, n_components=75, random_state=1)
# rbf_action_feature = RBFSampler(gamma=1, n_components=75, random_state=1)

# def phi(x):
#     """ x must be one or a set column vectors """
#     entry_0 = np.vstack(x[:,0])
#     assert entry_0.shape[0] >= entry_0.shape[1]
#     return rbf_state_feature.fit_transform(x.T).T

# def psi(u):
#     """ u must be one or a set of column vectors """
#     entry_0 = np.vstack(u[:,0])
#     assert entry_0.shape[0] >= entry_0.shape[1]
#     return rbf_action_feature.fit_transform(u.T).T

tensor = KoopmanTensor(
    X,
    Y,
    U,
    phi=observables.monomials(2), # 3
    psi=observables.monomials(2), # 3
    regressor='ols'
)

#%% Training error
print("\nTraining error:")

training_norms = np.zeros([X.shape[1]])

for i in range(X.shape[1]):
    x = np.vstack(X[:, i])
    phi_x = tensor.phi(x)

    predicted_x_prime = tensor.B.T @ tensor.K_(U[:, i]) @ phi_x
    true_x_prime = np.vstack(Y[:, i])

    training_norms[i] = utilities.l2_norm(true_x_prime, predicted_x_prime)

print("Mean training norm:", np.mean(training_norms))

#%% Define cost
def cost(x, u):
    # Assuming that data matrices are passed in for X and U. Columns vecs are snapshots
    mat = np.vstack(np.diag(x.T @ Q @ x)) + np.power(u, 2)*R
    return mat

# def reward_func(state, action):
#     #* assume state and action can be matrices where the columns are states/actions
#     x = state[0]
#     x_dot = state[1]
#     theta = state[2]
#     theta_dot = state[3]
#     # x, x_dot, theta, theta_dot = self.state
#     force = np.ones([state.shape[1]]) * -env.force_mag
#     force[np.where(action == 1)[0]] = env.force_mag
#     # force = env.force_mag if action == 1 else -env.force_mag
#     costheta = np.cos(theta)
#     sintheta = np.sin(theta)

#     # For the interested reader:
#     # https://coneural.org/florian/papers/05_cart_pole.pdf
#     temp = (
#         force + env.polemass_length * theta_dot ** 2 * sintheta
#     ) / env.total_mass
#     thetaacc = (env.gravity * sintheta - costheta * temp) / (
#         env.length * (4.0 / 3.0 - env.masspole * costheta ** 2 / env.total_mass)
#     )
#     xacc = temp - env.polemass_length * thetaacc * costheta / env.total_mass

#     if env.kinematics_integrator == "euler":
#         x = x + env.tau * x_dot
#         x_dot = x_dot + env.tau * xacc
#         theta = theta + env.tau * theta_dot
#         theta_dot = theta_dot + env.tau * thetaacc
#     else:  # semi-implicit euler
#         x_dot = x_dot + env.tau * xacc
#         x = x + env.tau * x_dot
#         theta_dot = theta_dot + env.tau * thetaacc
#         theta = theta + env.tau * theta_dot

#     # self.state = (x, x_dot, theta, theta_dot)

#     rewards = np.ones([state.shape[1]])
#     rewards[np.where(x < -env.x_threshold)] = 0.0
#     rewards[np.where(x > env.x_threshold)] = 0.0
#     rewards[np.where(theta < -env.theta_threshold_radians)] = 0.0
#     rewards[np.where(theta > env.theta_threshold_radians)] = 0.0

#     return rewards

# reward_func(np.array([[1, 1], [0, 0], [1, 1], [0, 0]]), np.array([[0, 0]]))

# def cost(x, u):
#     return -reward_func(x, u)

#%% Learn control
u_bounds = np.array([[0, 1]])
All_U = np.array([[0, 1]])
gamma = 0.5
lamb = 1.0
lr = 1e-1
epsilon = 4e-4

algos = algorithmsv2.algos(
    X,
    All_U,
    u_bounds[0],
    tensor,
    cost,
    gamma=gamma,
    epsilon=epsilon,
    bellman_error_type=0,
    learning_rate=lr,
    weight_regularization_bool=True,
    weight_regularization_lambda=lamb,
    optimizer='adam'
)

# algos.w = np.load('bellman-weights.npy')
# algos.w = np.array([
#     [-6.25794665e-01],
#     [-4.05142775e-03],
#     [-1.14685414e-03],
#     [ 1.22353767e-03],
#     [ 9.93027095e-04],
#     [ 1.93718097e+00],
#     [ 1.98265639e-01],
#     [-2.87556280e-01],
#     [ 1.24441079e-01],
#     [ 1.79162901e+00],
#     [ 8.67723760e-01],
#     [-3.18273490e-01],
#     [ 1.04168751e+00],
#     [ 7.99085284e-01],
#     [ 1.88380483e+00],
#     [ 1.40321488e+00],
#     [ 1.31128608e+00],
#     [ 8.63758080e-01],
#     [ 6.88648832e-01],
#     [ 6.85741896e-01],
#     [ 5.78663495e-01],
#     [ 1.07316362e+00],
#     [-1.31681602e+00],
#     [-1.49337352e-01],
#     [ 3.77608156e-01],
#     [ 5.11626221e-01],
#     [ 6.16237556e-02],
#     [ 9.61554647e-01],
#     [-1.82980532e+00],
#     [ 1.00552850e-01],
#     [ 5.72135426e-01],
#     [-1.58383704e+00],
#     [-3.13481480e-01],
#     [ 3.50395672e-03],
#     [ 9.79144522e-02]
# ])
# algos.w = np.array([
#     [-0.62659919],
#     [-0.00897014],
#     [-0.00959372],
#     [ 0.01252761],
#     [-0.00693892],
#     [ 1.90943469],
#     [ 0.1117488 ],
#     [-0.20447107],
#     [ 0.05952606],
#     [ 1.7917121 ],
#     [ 0.86840699],
#     [-0.32586552],
#     [ 1.0946938 ],
#     [ 0.70335887],
#     [ 1.89283258],
#     [ 0.74423775],
#     [ 0.78924267],
#     [ 0.56825446],
#     [ 0.69017369],
#     [ 0.33958384],
#     [ 0.10841765],
#     [ 1.00091402],
#     [-1.09894694],
#     [ 0.13813255],
#     [ 0.50455058],
#     [ 0.48329882],
#     [-0.20073181],
#     [ 0.86894308],
#     [-1.79097402],
#     [ 0.1235106 ],
#     [ 0.53904337],
#     [-1.64378235],
#     [-0.35879732],
#     [ 0.0086023 ],
#     [ 0.12826922]
# ])
print("Weights before updating:", algos.w)
bellmanErrors, gradientNorms = algos.algorithm2(batch_size=512)
print("Weights after updating:", algos.w)

#%% Extract policy
All_U_range = np.arange(All_U.shape[1])
def policy(x):
    pis = algos.pis(x)[:,0]
    # Select action column at index sampled from policy distribution
    u_ind = np.random.choice(All_U_range, p=pis)
    u = np.vstack(All_U[:,u_ind])
    return u[0,0]

def random_policy(x):
    return env.action_space.sample()

#%% Test policy by simulating system
num_episodes = 200
rewards = np.zeros([num_episodes])
for episode in range(num_episodes):
    x = np.vstack(env.reset())
    done = False
    while not done:
        # env.render()
        u = policy(x)

        next_state,reward,done,info = env.step(u)
        rewards[episode] += reward

        x = np.vstack(next_state)
print("Mean reward per episode:", np.mean(rewards))

#%%