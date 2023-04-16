# Imports
import matplotlib.pyplot as plt
import numpy as np
import sys

try:
    seed = int(sys.argv[1])
except:
    seed = 123
np.random.seed(seed)

from cost import Q, R, reference_point, cost
from dynamics import dt, state_dim, action_dim, state_minimums, state_maximums, f, continuous_A, continuous_B

sys.path.append('../../../')
from final.control.policies.lqr import LQRPolicy
# Variables
gamma = 0.99
reg_lambda = 1.0

plot_path = f'output/lqr/seed_{seed}/'
plot_file_extensions = ['svg', 'png']

# LQR Policy
lqr_policy = LQRPolicy(
    continuous_A,
    continuous_B,
    Q,
    R,
    reference_point,
    gamma,
    reg_lambda,
    dt=dt,
    is_continuous=True,
    seed=seed
)

# Test policy
def watch_agent(num_episodes, step_limit, specifiedEpisode=None):
    np.random.seed(seed)

    if specifiedEpisode is None:
        specifiedEpisode = num_episodes-1

    states = np.zeros([num_episodes,step_limit,state_dim])
    actions = np.zeros([num_episodes,step_limit,action_dim])
    costs = np.zeros([num_episodes,step_limit])

    initial_states = np.random.uniform(
        state_minimums,
        state_maximums,
        [state_dim, num_episodes]
    ).T

    for episode in range(num_episodes):
        state = np.vstack(initial_states[episode])

        for step in range(step_limit):
            states[episode,step] = state[:,0]

            action = lqr_policy.get_action(state)
            # if action[0,0] > action_range:
            #     action = np.array([[action_range]])
            # elif action[0,0] < -action_range:
            #     action = np.array([[-action_range]])
            actions[episode,step] = action

            costs[episode,step] = cost(state, action)[0,0]

            state = f(state, action)

    plt.title("Total Cost Per Episode")
    plt.xlabel("Episode #")
    plt.ylabel("Total Cost")
    plt.plot(costs.sum(1))
    for plot_file_extension in plot_file_extensions:
        plt.savefig(plot_path + 'total-cost-per-episode.' + plot_file_extension)
    # plt.show()
    plt.clf()

    print(f"Mean of total costs per episode over {num_episodes} episode(s): {costs.sum(1).mean()}")
    print(f"Standard deviation of total costs per episode over {num_episodes} episode(s): {costs.sum(1).std()}\n")

    print(f"Initial state of episode #{specifiedEpisode}: {states[specifiedEpisode,0]}")
    print(f"Final state of episode #{specifiedEpisode}: {states[specifiedEpisode,-1]}\n")

    print(f"Reference state: {reference_point[:,0]}\n")

    print(f"Difference between final state of episode #{specifiedEpisode} and reference state: {np.abs(states[specifiedEpisode,-1] - reference_point[:,0])}")
    print(f"Norm between final state of episode #{specifiedEpisode} and reference state: {np.linalg.norm(states[specifiedEpisode,-1] - reference_point[:,0])}\n")

    # Plot dynamics over time for all state dimensions for both controllers
    plt.title("Dynamics Over Time")
    plt.xlabel("Timestamp")
    plt.ylabel("State value")

    # Create and assign labels as a function of number of dimensions of state
    labels = []
    for i in range(state_dim):
        labels.append(f"x_{i}")
        plt.plot(states[specifiedEpisode,:,i], label=labels[i])
    plt.legend(labels)
    plt.tight_layout()
    for plot_file_extension in plot_file_extensions:
        plt.savefig(plot_path + 'states-over-time.' + plot_file_extension)
    # plt.show()
    plt.clf()

    # Plot x_0 vs x_1
    plt.title(f"Controllers in Environment (2D; Episode #{specifiedEpisode})")
    plt.xlim(state_minimums[0,0], state_maximums[0,0])
    plt.ylim(state_minimums[0,0], state_maximums[0,0])
    plt.plot(
        states[specifiedEpisode,:,0],
        states[specifiedEpisode,:,1],
        'gray'
    )
    for plot_file_extension in plot_file_extensions:
        plt.savefig(plot_path + 'x0-vs-x1.' + plot_file_extension)
    # plt.show()
    plt.clf()

    # Plot histogram of actions over time
    plt.title(f"Histogram of Actions Over Time (Episode #{specifiedEpisode})")
    plt.xlabel("Action Value")
    plt.ylabel("Frequency")
    plt.hist(actions[specifiedEpisode,:,0])
    for plot_file_extension in plot_file_extensions:
        plt.savefig(plot_path + 'actions-histogram.' + plot_file_extension)
    # plt.show()
    plt.clf()

    # Plot scatter plot of actions over time
    plt.title(f"Scatter Plot of Actions Over Time (Episode #{specifiedEpisode})")
    plt.xlabel("Step #")
    plt.ylabel("Action Value")
    plt.scatter(np.arange(actions.shape[1]), actions[specifiedEpisode,:,0], s=5)
    for plot_file_extension in plot_file_extensions:
        plt.savefig(plot_path + 'actions-scatter-plot.' + plot_file_extension)
    # plt.show()
    plt.clf()

print("\nTesting learned policy...\n")
watch_agent(num_episodes=100, step_limit=int(25.0 / dt), specifiedEpisode=42)